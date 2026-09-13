"""Pure retained-evidence correlation tests; no game or production oracle."""

import copy
from pathlib import Path

import pytest

from fort_gym.bench.production_brew_evidence import summarize_brew_evidence
from fort_gym.bench.production_brew_fixture import REACTION
from fort_gym.bench.production_observer_probe import (
    ProductionObserverProbe,
    validate_boundary,
)
from tests.test_production_brew_fixture import receipt
from tests.test_production_observer_probe import OWNER, boundary


def reaction(sequence=1, item_id=42, units=5):
    return {
        "kind": "reaction_output_observation",
        "sequence": sequence,
        "reaction_code": REACTION,
        "worker_id": 19,
        "worker_job": {
            "status": "observed",
            "job_id": 100,
            "job_type": "CustomReaction",
            "reaction_name": REACTION,
            "building_holder_id": 7,
            "assigned_worker_id": 19,
        },
        "vector_scope": "cumulative_outputs_at_callback",
        "output_items": [
            {"item_id": item_id, "resource": "drink", "units_at_observation": units}
        ],
    }


def inputs(events=None):
    start = {"year": 30, "year_tick": 100, "pause_state": True}
    end = {**start, "year_tick": 350}
    observer = ProductionObserverProbe(Path("/game"), OWNER)
    queued = receipt(observer, start)
    baseline = boundary()
    baseline["events"]["events"] = []
    baseline["inventory"]["items"] = []
    endpoint = boundary(tick=350)
    endpoint["events"].update(
        start=copy.deepcopy(baseline["events"]["start"]),
        events=copy.deepcopy(events or []),
        observed_events=len(events or []),
    )
    endpoint["inventory"].update(
        observer_start=copy.deepcopy(baseline["events"]["start"]),
        items=[],
        event_sequence=len(events or []),
    )
    validate_boundary(baseline, start, observer.runtime, OWNER)
    validate_boundary(endpoint, end, observer.runtime, OWNER)
    return queued, baseline, endpoint


def test_exact_job_workshop_and_worker_match_without_summing_cumulative_outputs():
    first, second = reaction(), reaction(2, units=3)
    second["output_items"].append(
        {"item_id": 43, "resource": "other", "units_at_observation": 1}
    )
    queued, baseline, endpoint = inputs([first, second])
    baseline["inventory"]["items"] = [{"item_id": 42}]
    endpoint["inventory"]["items"] = [{"item_id": 43}]
    unchanged = copy.deepcopy((queued, baseline, endpoint))
    result = summarize_brew_evidence(queued, baseline, endpoint)
    assert result["matching_reaction_sequences"] == [1, 2]
    assert result["matching_native_fields_observed"]
    assert (
        not result["native_binding_validated"]
        and not result["independent_production_oracle"]
    )
    assert result["production_quantity"] is None
    a, b = result["output_item_observations"]
    assert a["item_id"] == 42 and a["present_in_baseline_inventory"]
    assert not a["present_in_endpoint_inventory"]
    assert [record["units_at_observation"] for record in a["observations"]] == [5, 3]
    assert b["observations"][0]["resource"] == "other"
    assert not b["present_in_baseline_inventory"] and b["present_in_endpoint_inventory"]
    assert result["inventory_absence_is_not_loss_or_consumption"]
    result["output_item_observations"][0]["observations"][0]["units_at_observation"] = (
        999
    )
    assert (queued, baseline, endpoint) == unchanged


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "no_current_job"),
        ("job_id", 101),
        ("job_id", True),
        ("job_type", "Other"),
        ("reaction_name", "Other"),
        ("building_holder_id", 8),
        ("building_holder_id", False),
        ("assigned_worker_id", 20),
        ("assigned_worker_id", False),
    ],
)
def test_partial_or_conflicting_context_is_not_a_match(field, value):
    event = reaction()
    event["worker_job"][field] = value
    result = summarize_brew_evidence(*inputs([event]))
    assert not result["matching_native_fields_observed"]
    assert result["unmatched_brewing_sequences"] == [1]
    assert result["production_quantity"] is None


def test_completion_notification_alone_is_not_brewing_output():
    events = [{"kind": "job_completion_notification", "job_id": 100, "sequence": 1}]
    result = summarize_brew_evidence(*inputs(events))
    assert result["job_completion_notification_sequences"] == [1]
    assert result["matching_reaction_sequences"] == []
    assert result["production_quantity"] is None


def test_unrelated_jobs_and_callback_workers_are_not_matched():
    event = reaction()
    event["worker_id"] = False
    result = summarize_brew_evidence(*inputs([event]))
    assert result["unmatched_brewing_sequences"] == [1]
    event["reaction_code"] = "OTHER_REACTION"
    result = summarize_brew_evidence(*inputs([event]))
    assert result["unmatched_brewing_sequences"] == []
    assert not result["matching_native_fields_observed"]


def test_baseline_events_are_not_counted_again_and_prefix_is_required():
    queued, baseline, endpoint = inputs([reaction()])
    baseline["events"]["events"] = copy.deepcopy(endpoint["events"]["events"])
    baseline["events"]["observed_events"] = 1
    assert not summarize_brew_evidence(queued, baseline, endpoint)[
        "matching_native_fields_observed"
    ]
    endpoint["events"]["events"][0]["worker_id"] = 20
    with pytest.raises(ValueError, match="prefix"):
        summarize_brew_evidence(queued, baseline, endpoint)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda q, b, e: q.update(ok=False),
        lambda q, b, e: q.update(quantity=True),
        lambda q, b, e: q.update(jobs_queued=True),
        lambda q, b, e: q.update(queue_before=1),
        lambda q, b, e: q.update(queue_after=2),
        lambda q, b, e: q.update(before={}),
        lambda q, b, e: q.update(created_job_ids=[True]),
        lambda q, b, e: q.update(workshop_id=False),
        lambda q, b, e: e.update(owner="other"),
        lambda q, b, e: e["events"].update(collector_records_complete=False),
        lambda q, b, e: e["inventory"].update(complete=False),
        lambda q, b, e: e["events"].update(native_coverage_validated=True),
        lambda q, b, e: e["events"].update(observed_events=2),
        lambda q, b, e: e["events"].update(
            events=[reaction()] * 257, observed_events=257
        ),
        lambda q, b, e: e["events"].update(observed_events=True),
        lambda q, b, e: e["events"].update(start={}),
        lambda q, b, e: e["events"]["events"][0].update(sequence=2),
        lambda q, b, e: e["events"]["events"][0].update(sequence=True),
        lambda q, b, e: e["events"]["events"][0].update(vector_scope="new_products"),
        lambda q, b, e: e["events"]["events"][0].update(output_items=[]),
        lambda q, b, e: e["events"]["events"][0].update(
            output_items=[reaction()["output_items"][0]] * 33
        ),
        lambda q, b, e: e["events"]["events"][0]["output_items"][0].update(
            item_id=True
        ),
        lambda q, b, e: e["events"]["events"][0]["output_items"][0].update(
            units_at_observation=True
        ),
        lambda q, b, e: e["inventory"].update(items=[{"item_id": 42}, {"item_id": 42}]),
        lambda q, b, e: e["inventory"].update(items=[{"item_id": 42}] * 8193),
    ],
)
def test_incomplete_or_malformed_evidence_cannot_be_summarized(mutation):
    args = inputs([reaction()])
    mutation(*args)
    with pytest.raises(ValueError):
        summarize_brew_evidence(*args)


def test_duplicate_output_ids_and_zero_units_remain_observations_not_total_yield():
    event = reaction(units=0)
    event["output_items"].append(copy.deepcopy(event["output_items"][0]))
    result = summarize_brew_evidence(*inputs([event]))
    records = result["output_item_observations"]
    assert len(records) == 1 and len(records[0]["observations"]) == 2
    assert all(
        value["units_at_observation"] == 0 for value in records[0]["observations"]
    )
    assert result["production_quantity"] is None
