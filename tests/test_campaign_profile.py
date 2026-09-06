from copy import deepcopy
import hashlib
import json

import pytest

from fort_gym.bench.eval.campaign import TICKS_PER_YEAR
from fort_gym.bench.eval.campaign_profile import campaign_profile, metrics_from_state, usage_profile


def state(tick=0, population=7, food=45):
    return {
        "year": 30 + tick // TICKS_PER_YEAR,
        "year_tick": tick % TICKS_PER_YEAR,
        "population": population,
        "stocks": {"food": food, "drink": 60, "wood": 3, "stone": 0},
        "campaign_observation_quality": {
            "schema_version": "fortgym.campaign-observation-quality/v1",
            "native_population_resources_validated": True,
        },
        "fort": {
            "ok": True,
            "building_scan_complete": True,
            "component_scan_truncated": False,
            "spaces_truncated": False,
            "functional_rooms": 2,
        },
        "crew": {
            "ok": True,
            "building_evidence_complete": True,
            "placed_furniture_completed": {"bed": 4},
            "workshops_truncated": False,
            "workshops": [
                {"built": True, "stage_read_ok": True},
                {"built": False, "stage_read_ok": True},
            ],
            "farm_plot_details_truncated": False,
            "farm_plot_details": [{"built": True, "stage_read_ok": True}],
            "death_evidence_complete": True,
            "dead_citizen_count": 2,
        },
    }


def row(step=0, start=0, end=100, *, before=None, after=None, accepted=True, kind="WAIT"):
    before, after = before or state(start), after or state(end)
    return {
        "run_id": "campaign",
        "step": step,
        "observation": before,
        "state_after_advance": after,
        "action": {"type": kind, "params": {}},
        "execute": {"accepted": accepted},
        "tick_advance": {
            "start_year": before["year"],
            "start_tick": before["year_tick"],
            "end_year": after["year"],
            "end_tick": after["year_tick"],
            "ticks_advanced": end - start,
        },
    }


def profile(rows, **kwargs):
    return campaign_profile(
        rows,
        campaign_id="campaign",
        status=kwargs.pop("status", "bounded_segment_complete"),
        usage=kwargs.pop("usage", None),
        terminal_state=kwargs.pop(
            "terminal_state", rows[-1]["state_after_advance"] if rows else None
        ),
        **kwargs,
    )


def test_profile_tracks_observed_growth_without_turning_reserves_into_production():
    rows = [
        row(after=state(100, population=6, food=30)),
        row(
            1,
            100,
            200,
            before=state(100, population=6, food=30),
            after=state(200, population=9, food=50),
        ),
    ]
    result = profile(rows)
    population = result["metrics"]["population"]
    assert (population["start"], population["end"], population["change"]) == (7, 9, 2)
    assert population["minimum_observed"] == 6 and population["maximum_observed"] == 9
    assert result["metrics"]["food_stock"]["change"] == 5
    assert result["flow_measurement"]["production"] is None
    assert result["metrics"]["completed_workshops"]["end"] == 1
    assert result["metrics"]["completed_farms"]["end"] == 1
    assert result["progress"]["elapsed_ticks"] == 200
    assert len(result["timeline"]) == 3


def test_zero_is_known_only_with_strict_native_observation_provenance():
    native = state(population=0, food=0)
    assert metrics_from_state(native)["population"] == 0
    del native["campaign_observation_quality"]
    unknown = metrics_from_state(native)
    assert unknown["population"] is None and unknown["food_stock"] is None


@pytest.mark.parametrize("field", ["population", "food"])
@pytest.mark.parametrize("value", [True, False, -1, "7", None])
def test_malformed_counts_never_become_measured_numbers(field, value):
    native = state()
    target = native if field == "population" else native["stocks"]
    target[field] = value
    key = "population" if field == "population" else "food_stock"
    assert metrics_from_state(native)[key] is None


@pytest.mark.parametrize(
    "section,field,key,value",
    [
        ("fort", "building_scan_complete", "functional_rooms", False),
        ("fort", "component_scan_truncated", "functional_rooms", True),
        ("fort", "spaces_truncated", "functional_rooms", True),
        ("crew", "building_evidence_complete", "completed_beds", False),
        ("crew", "workshops_truncated", "completed_workshops", True),
        ("crew", "farm_plot_details_truncated", "completed_farms", True),
        ("crew", "death_evidence_complete", "recorded_dead_citizens", False),
    ],
)
def test_incomplete_native_scans_do_not_become_zero_or_complete_totals(section, field, key, value):
    native = state()
    native[section][field] = value
    assert metrics_from_state(native)[key] is None


def test_missing_final_observation_does_not_report_stale_healthy_values():
    result = profile([row()], terminal_state=None, status="failed")
    population = result["metrics"]["population"]
    assert population["end"] is None and population["change"] is None
    assert population["minimum_observed"] == 7
    assert population["missing_samples"] == 1
    assert result["segment_status"] == "failed"
    assert result["fortress_collapse"] == "not_assessed"


def test_calendar_anniversary_and_budget_pause_do_not_decide_gameplay_success():
    result = profile([row(end=TICKS_PER_YEAR)], status="budget_limited_pause")
    assert result["progress"]["year_two_reached"] is True
    assert result["functioning_fortress"] == "not_assessed"
    assert result["autonomous_gameplay"] == "not_assessed"
    assert result["fortress_collapse"] == "not_assessed"


def test_acceptance_and_command_change_are_not_completed_work_or_adaptation_verdicts():
    rows = [row(accepted=False, kind="BUILD"), row(1, 100, 200, kind="DIG")]
    result = profile(rows)
    assert result["actions"]["accepted"] == 1 and result["actions"]["rejected"] == 1
    assert result["actions"]["changed_command_after_rejection"] == 1
    assert result["metrics"]["completed_workshops"]["change"] == 0


def test_adapter_readiness_rejection_is_counted_without_claiming_illegal_placement():
    blocked = row(accepted=False, kind="BUILD", end=0)
    blocked["execute"]["why"] = "path_cache_stale"
    result = profile([blocked])
    assert result["actions"]["rejected"] == 1
    assert result["actions"]["path_cache_stale_rejections"] == 1
    assert result["progress"]["elapsed_ticks"] == 0
    assert result["fortress_collapse"] == "not_assessed"
    blocked["execute"]["why"] = "tile_not_designatable"
    assert profile([blocked])["actions"]["path_cache_stale_rejections"] == 0


def test_time_needs_the_canonical_prefix_and_native_calendar():
    rows = [row(step=3)]
    assert profile(rows)["progress"]["elapsed_ticks"] is None
    rows = [row()]
    del rows[0]["tick_advance"]["start_year"]
    assert "missing_native_calendar" in profile(rows)["progress"]["profile_time_issues"]


def test_profiles_reject_mixed_campaigns_and_do_not_double_count_duplicate_trace_prefixes():
    rows = [row(), row()]
    assert profile(rows)["progress"]["elapsed_ticks"] is None
    rows[1]["run_id"] = "different"
    with pytest.raises(ValueError, match="different trace identities"):
        profile(rows)


def test_reported_usage_is_cumulative_and_unknown_dispatches_are_not_free():
    result = usage_profile(
        {
            "total_cost_usd": "0.003462525",
            "total_tokens": 31965,
            "dispatched_requests": 6,
            "returned_responses": 3,
            "accounted_responses": 3,
        }
    )
    assert result["reported_model_cost_usd"] == "0.003462525"
    assert result["dispatches_without_returned_usage"] == 3
    assert result["billing_reconciled"] is False
    assert usage_profile({"total_cost_usd": "NaN"})["reported_model_cost_usd"] is None
    assert usage_profile(None)["reported_model_cost_usd"] is None


def test_profile_does_not_mutate_or_publish_full_native_or_agent_state():
    rows = [row()]
    rows[0]["observation"]["private_note"] = "must-not-publish"
    original = deepcopy(rows)
    result = profile(rows)
    assert rows == original
    assert "must-not-publish" not in str(result)


def retained_segment(tmp_path):
    trace = tmp_path / "campaign/trace.jsonl"
    trace.parent.mkdir()
    record = row()
    trace.write_text(json.dumps(record) + "\n")
    segment = {
        "schema_version": "fortgym.campaign-segment/v1",
        "segment_id": "test-segment",
        "campaign_id": "campaign",
        "model": "test/model",
        "condition_id": "test-condition",
        "configuration": {"test_only": True},
        "code_revision": "a" * 40,
        "status": "bounded_segment_complete",
        "native_start": record["observation"],
        "native_final": record["state_after_advance"],
        "usage": {"total_cost_usd": "0", "dispatched_requests": 0, "returned_responses": 0},
        "private_memory": "must-not-publish",
    }
    (tmp_path / "campaign-segment.json").write_text(json.dumps(segment))
    runtime = {
        "schema_version": "fortgym.isolated-experiment-runtime/v1",
        "code_revision": "a" * 40,
        "native_load_verified": True,
        "cleanup_verified": True,
        "runtime_path": "/private/runtime",
    }
    (tmp_path / "result.json").write_text(json.dumps(runtime))
    return tmp_path


def test_retained_segment_report_is_read_only_source_bound_and_excludes_private_fields(tmp_path):
    from scripts.campaign_profile import report_segment

    root = retained_segment(tmp_path)
    sources = {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*.json*")}
    result = report_segment(root)
    assert result["metrics"]["population"]["end"] == 7
    assert result["runtime"]["cleanup_verified"] is True
    assert result["comparison_rankings_available"] is False
    assert result["source_sha256"] == {
        name: hashlib.sha256(data).hexdigest() for name, data in sources.items()
    }
    assert all((root / name).read_bytes() == data for name, data in sources.items())
    assert "must-not-publish" not in str(result) and "/private/runtime" not in str(result)


def test_retained_report_rejects_mismatched_runtime_revision(tmp_path):
    from scripts.campaign_profile import report_segment

    root = retained_segment(tmp_path)
    runtime_path = root / "result.json"
    runtime = json.loads(runtime_path.read_text())
    runtime["code_revision"] = "b" * 40
    runtime_path.write_text(json.dumps(runtime))
    with pytest.raises(ValueError, match="identity"):
        report_segment(root)
