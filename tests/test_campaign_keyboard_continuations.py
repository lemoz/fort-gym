import json

import pytest

from fort_gym.bench.api import campaign_keyboard_records as records
from tests.test_campaign_keyboard_records import evidence_root as evidence_root


def test_continuation_preserves_parent_usage_and_only_exports_operational_fields(evidence_root):
    path = evidence_root / "experiments/evidence" / records.CONTINUATIONS[0]
    source = json.loads(path.read_text())
    source["model_memory"] = source["screen"] = "private-content"
    source["checkpoints"][0]["native_save"] = "private-save"
    path.write_text(json.dumps(source))
    data = records.keyboard_campaign_records(evidence_root)
    row = data["continuations"][0]
    assert row["checkpoint_cursor"] == 296
    assert row["progress"]["cumulative_model_responses"] == 312
    assert row["progress"]["new_model_calls"] == 64
    assert row["progress"]["retained_elapsed_ticks"] == 63600
    assert row["usage"]["all_attempt_tokens"] == 10284908
    assert row["usage"]["reported_charge_usd"] is None
    assert row["final_checkpoint_fresh_reload_verified"] is False
    assert row["new_restart_performed"] is row["uninterrupted_campaign"] is False
    assert row["teardown_verified"] is True
    assert data["checkpoint_recoveries"][-1]["checkpoint_cursor"] == 232
    assert data["checkpoint_failures"][0]["newer_native_state_resumable"] is False
    assert "private-" not in json.dumps(data)


@pytest.mark.parametrize("field,value", [
    ("parent_record", "missing"), ("parent_checkpoint_sha256", "a" * 64),
    ("parent_checkpoint_cursor", 216), ("snapshot_profile", "native_menu_preserving_save/v2"),
    ("source_revision", "wrong"), ("model", "other"), ("captured_screen_size", [80, 25]),
    ("new_model_calls", True), ("new_model_calls", 63), ("new_accepted_decisions", 65),
    ("new_elapsed_ticks", 14401), ("retained_elapsed_ticks", 63601),
    ("new_tokens", 1), ("campaign_tokens", 1), ("all_attempt_tokens", 10215904),
    ("cumulative_model_responses", 296), ("discarded_native_ticks", 0),
    ("native_save_loss_restarts", 0), ("reported_charge_usd", 0),
    ("independent_retained_evidence_audit_passed", 1), ("teardown_verified", False),
    ("original_checkpoint_unchanged", False), ("inherited_discontinuity_unchanged", False),
    ("memory_and_usage_preserved_across_segments", False),
    ("reset_memory", True), ("reset_usage", True), ("strategy_intervention", True),
    ("new_restart_performed", True), ("uninterrupted_campaign", True),
    ("historical_failed_run_reclassified_as_success", True),
    ("final_checkpoint_fresh_reload_verified", True), ("steps_per_segment", False),
    ("steps_per_segment", 65), ("checkpoints", []),
])
def test_continuation_rejects_usage_reset_and_invented_proof(evidence_root, field, value):
    path = evidence_root / "experiments/evidence" / records.CONTINUATIONS[0]
    source = json.loads(path.read_text())
    source[field] = value
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError):
        records.keyboard_campaign_records(evidence_root)


@pytest.mark.parametrize("field,value", [
    ("cursor", 263), ("cursor", True), ("elapsed_native_ticks", 50000),
    ("sha256", "not-a-hash"), ("parent_sha256", "a" * 64), ("checkpoint_verified", 1),
])
def test_continuation_cannot_skip_or_reorder_checkpoint_lineage(evidence_root, field, value):
    path = evidence_root / "experiments/evidence" / records.CONTINUATIONS[0]
    source = json.loads(path.read_text())
    source["checkpoints"][1][field] = value
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError):
        records.keyboard_campaign_records(evidence_root)


def test_later_continuation_binds_previous_continuation_and_is_not_independent(evidence_root, monkeypatch):
    folder = evidence_root / "experiments/evidence"
    source = json.loads((folder / records.CONTINUATIONS[0]).read_text())
    parent = records.keyboard_campaign_records(evidence_root)["continuations"][0]
    source.update(
        parent_record=parent["continuation_id"], parent_checkpoint_sha256=parent["checkpoint_sha256"],
        parent_checkpoint_cursor=296, steps_per_segment=64, cumulative_model_responses=376,
        new_elapsed_ticks=1000, retained_elapsed_ticks=64600, new_tokens=100,
        campaign_tokens=10216004, all_attempt_tokens=10285008,
        checkpoints=[{"cursor": 360, "sha256": "a" * 64,
                      "parent_sha256": parent["checkpoint_sha256"],
                      "elapsed_native_ticks": 64600, "checkpoint_verified": True}],
    )
    filename = "synthetic-continuation-test.json"
    (folder / filename).write_text(json.dumps(source))
    monkeypatch.setattr(records, "CONTINUATIONS", (*records.CONTINUATIONS, filename))
    row = records.keyboard_campaign_records(evidence_root)["continuations"][-1]
    assert row["checkpoint_cursor"] == 360
    assert row["parent_record"] == parent["continuation_id"]
    assert row["progress"]["cumulative_model_responses"] == 376
    assert row["progress"]["discarded_native_ticks"] == 2000
    assert row["usage"]["all_attempt_tokens"] == 10285008
    assert row["uninterrupted_campaign"] is False


def test_completed_play_after_recovery_keeps_all_responses_and_safe_outcome_counts(evidence_root):
    path = evidence_root / "experiments/evidence" / records.CONTINUATIONS[1]
    source = json.loads(path.read_text())
    source["outcome_counts"]["screen"] = "private-screen"
    source["outcome_counts"]["counts"]["population"]["position"] = "private-position"
    path.write_text(json.dumps(source))
    data = records.keyboard_campaign_records(evidence_root)
    row = data["continuations"][1]
    assert row["parent_record"] == data["tail_recoveries"][0]["recovery_id"]
    assert row["checkpoint_cursor"] == 375
    assert row["progress"]["cumulative_model_responses"] == 391
    assert row["progress"]["retained_elapsed_ticks"] == 77000
    assert row["usage"]["campaign_tokens"] == 12838159
    assert row["outcome_counts"]["counts"]["completed_farms"] == {"start": 2, "end": 4}
    assert row["outcome_counts"]["food_stock"] is None
    assert {"kind": "continuation", "id": row["continuation_id"]} in data["continuation_events"]
    assert "private-" not in json.dumps(data)


@pytest.mark.parametrize("field,value", [
    ("independent_private_review_passed", False), ("food_stock", 45),
    ("advancing_decisions", True), ("zero_tick_decisions", 56),
    ("production_and_consumption", "self_sufficient"), ("sustainability", "proved"),
])
def test_outcome_summary_cannot_invent_measurement(evidence_root, field, value):
    path = evidence_root / "experiments/evidence" / records.CONTINUATIONS[1]
    source = json.loads(path.read_text())
    source["outcome_counts"][field] = value
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError):
        records.keyboard_campaign_records(evidence_root)


@pytest.mark.parametrize("value", [True, -1, "4", None])
def test_outcome_counts_require_actual_integer_values(evidence_root, value):
    path = evidence_root / "experiments/evidence" / records.CONTINUATIONS[1]
    source = json.loads(path.read_text())
    source["outcome_counts"]["counts"]["completed_farms"]["end"] = value
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError):
        records.keyboard_campaign_records(evidence_root)


def test_completed_keyboard_play_distinguishes_rejections_and_requested_from_actual_time(evidence_root):
    path = evidence_root / "experiments/evidence" / records.CONTINUATIONS[2]
    source = json.loads(path.read_text())
    source["execution_counts"]["screen"] = "private-execution-content"
    path.write_text(json.dumps(source))
    data = records.keyboard_campaign_records(evidence_root)
    row = data["continuations"][2]
    assert row["checkpoint_cursor"] == 439
    assert row["parent_record"] == data["continuations"][1]["continuation_id"]
    assert row["progress"]["cumulative_model_responses"] == 455
    assert row["progress"]["new_accepted_decisions"] == 63
    assert row["progress"]["new_elapsed_ticks"] == 24000
    assert row["progress"]["retained_elapsed_ticks"] == 101000
    assert row["usage"]["campaign_tokens"] == 14814687
    assert row["usage"]["all_attempt_tokens"] == 14883691
    assert row["execution_counts"] == {
        "requested_elapsed_ticks": 26000, "model_input_rejections": 1,
        "rejected_native_key_events": 0, "menu_deferrals": 1, "clock_unavailable_timeouts": 0,
    }
    assert row["outcome_counts"]["zero_tick_decisions"] == 52
    assert row["outcome_counts"]["counts"]["completed_beds"] == {"start": 3, "end": 4}
    assert {"kind": "continuation", "id": row["continuation_id"]} in data["continuation_events"]
    assert "private-" not in json.dumps(data)


@pytest.mark.parametrize("field,value", [
    ("schema_version", "other"), ("independent_private_review_passed", 1),
    ("requested_elapsed_ticks", 23999), ("requested_elapsed_ticks", True),
    ("model_input_rejections", 0), ("model_input_rejections", "1"),
    ("rejected_native_key_events", 1), ("menu_deferrals", 52),
    ("clock_unavailable_timeouts", -1), ("clock_unavailable_timeouts", 63),
])
def test_execution_counts_cannot_invent_time_or_hide_input_dispatch(evidence_root, field, value):
    path = evidence_root / "experiments/evidence" / records.CONTINUATIONS[2]
    source = json.loads(path.read_text())
    source["execution_counts"][field] = value
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError):
        records.keyboard_campaign_records(evidence_root)


def test_next_completed_window_preserves_lineage_without_inventing_branch_coverage(evidence_root):
    path = evidence_root / "experiments/evidence" / records.CONTINUATIONS[3]
    source = json.loads(path.read_text())
    source["execution_counts"]["native_capture"] = "private-clock-content"
    source["outcome_counts"]["counts"]["drink_units"]["items"] = "private-item-content"
    path.write_text(json.dumps(source))
    data = records.keyboard_campaign_records(evidence_root)
    parent, row = data["continuations"][2:4]
    assert row["parent_record"] == parent["continuation_id"]
    assert row["checkpoints"][0]["parent_sha256"] == parent["checkpoint_sha256"]
    assert row["checkpoint_cursor"] == 503
    assert row["progress"]["cumulative_model_responses"] == 519
    assert row["progress"]["new_accepted_decisions"] == 64
    assert row["progress"]["new_elapsed_ticks"] == 14000
    assert row["progress"]["retained_elapsed_ticks"] == 115000
    assert row["usage"]["campaign_tokens"] == 16682250
    assert row["usage"]["all_attempt_tokens"] == 16751254
    assert row["execution_counts"] == {
        "requested_elapsed_ticks": 14000, "model_input_rejections": 0,
        "rejected_native_key_events": 0, "menu_deferrals": 0, "clock_unavailable_timeouts": 0,
    }
    assert row["outcome_counts"]["counts"]["drink_units"] == {"start": 162, "end": 172}
    assert row["outcome_counts"]["advancing_decisions"] == 7
    assert row["outcome_counts"]["zero_tick_decisions"] == 57
    assert row["outcome_counts"]["food_stock"] is None
    assert row["final_checkpoint_fresh_reload_verified"] is False
    assert row["uninterrupted_campaign"] is row["new_restart_performed"] is False
    events = [{"kind": "continuation", "id": item["continuation_id"]} for item in (parent, row)]
    offset = data["continuation_events"].index(events[0])
    assert data["continuation_events"][offset:offset + 2] == events
    assert "private-" not in json.dumps(data)


def test_native_completion_preserves_outer_runner_failure(evidence_root):
    path = evidence_root / "experiments/evidence" / records.CONTINUATIONS[4]
    source = json.loads(path.read_text())
    source["operator_observation_warning"]["raw_error"] = "private-command-path"
    path.write_text(json.dumps(source))
    data = records.keyboard_campaign_records(evidence_root)
    parent, row = data["continuations"][3:5]
    assert row["parent_record"] == parent["continuation_id"]
    assert row["checkpoint_cursor"] == 567
    assert row["progress"]["retained_elapsed_ticks"] == 122200
    assert row["progress"]["new_elapsed_ticks"] == 7200
    assert row["progress"]["cumulative_model_responses"] == 583
    assert row["usage"]["campaign_tokens"] == 18636365
    assert row["usage"]["all_attempt_tokens"] == 18705369
    assert row["outcome_counts"]["counts"]["population"] == {"start": 7, "end": 12}
    assert row["outcome_counts"]["counts"]["drink_units"] == {"start": 172, "end": 181}
    assert row["outcome_counts"]["advancing_decisions"] == 4
    assert row["outcome_counts"]["zero_tick_decisions"] == 60
    assert row["outcome_counts"]["food_stock"] is None
    assert row["operator_status"] == "failed"
    assert row["operator_observation_warning"] == {
        "operator_status": "failed", "native_window_status": "completed",
        "kind": "exchange_observation_error", "command_exit_code": 137,
        "underlying_cause": "unverified", "original_error_retained": True,
    }
    assert row["teardown_verified"] is True
    assert row["new_restart_performed"] is row["uninterrupted_campaign"] is False
    assert "private-" not in json.dumps(data)
    assert {"kind": "continuation", "id": row["continuation_id"]} in data["continuation_events"]


@pytest.mark.parametrize("field,value", [
    ("operator_status", "completed"), ("native_window_status", "failed"),
    ("kind", "no_error"), ("command_exit_code", 0), ("command_exit_code", "137"),
    ("underlying_cause", "exit_race"), ("original_error_retained", 1),
    ("original_error_retained", False),
])
def test_operator_warning_cannot_hide_error_or_invent_cause(evidence_root, field, value):
    path = evidence_root / "experiments/evidence" / records.CONTINUATIONS[4]
    source = json.loads(path.read_text())
    source["operator_observation_warning"][field] = value
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError):
        records.keyboard_campaign_records(evidence_root)


@pytest.mark.parametrize("field,value", [
    ("operator_status", "completed"), ("operator_status", None),
    ("operator_observation_warning", None), ("operator_observation_warning", {}),
    ("schema_version", "fortgym.native-keyboard-continuation-summary/v1"),
    ("schema_version", "fortgym.native-keyboard-continuation-summary/v3"),
])
def test_warning_publication_requires_explicit_schema_and_operator_state(evidence_root, field, value):
    path = evidence_root / "experiments/evidence" / records.CONTINUATIONS[4]
    source = json.loads(path.read_text())
    source[field] = value
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError):
        records.keyboard_campaign_records(evidence_root)


def test_declared_next_window_keeps_model_and_all_budget_state():
    from fort_gym.bench.run.keyboard_config import load_window

    root = records.PROJECT_ROOT
    condition = root / "experiments/campaign_astra_keyboard_20260907.json"
    before, previous = load_window(condition, root / "experiments/campaign_astra_keyboard_window_20260908l.json")
    after, following = load_window(condition, root / "experiments/campaign_astra_keyboard_window_20260908m.json")
    assert before == after
    assert previous["continuation_from_next_step"] == 439
    assert following["continuation_from_next_step"] == 503
    assert following["steps_per_segment"] == previous["steps_per_segment"] == 64
    assert following["max_segments"] == previous["max_segments"] == 1
    assert following["snapshot_profile"] == previous["snapshot_profile"]
    assert all(following[key] is False for key in ("reset_memory", "reset_usage", "strategy_intervention"))
    assert "budget_extension" not in following and "restart" not in following


def test_measured_food_window_preserves_history_and_actual_completed_development(evidence_root):
    data = records.keyboard_campaign_records(evidence_root)
    parent, row = data["continuations"][4:6]
    assert row["parent_record"] == parent["continuation_id"]
    assert row["checkpoints"][0]["parent_sha256"] == parent["checkpoint_sha256"]
    assert row["checkpoint_cursor"] == 631
    assert row["progress"]["new_accepted_decisions"] == row["progress"]["new_model_calls"] == 64
    assert row["progress"]["cumulative_model_responses"] == 647
    assert row["progress"]["retained_elapsed_ticks"] == 143400
    assert row["progress"]["new_elapsed_ticks"] == 21200
    assert row["usage"]["new_tokens"] == 2213858
    assert row["usage"]["campaign_tokens"] == 20850223
    assert row["usage"]["all_attempt_tokens"] == 20919227
    assert row["usage"]["reported_charge_usd"] is None
    assert row["outcome_counts"]["counts"] == {
        "population": {"start": 12, "end": 12},
        "completed_farms": {"start": 5, "end": 7},
        "completed_beds": {"start": 4, "end": 5},
        "completed_workshops": {"start": 3, "end": 4},
        "recorded_dead_citizens": {"start": 0, "end": 0},
        "drink_units": {"start": 181, "end": 179},
    }
    food = row["food_inventory"]
    assert food["initial_checkpoint_cursor"] == 567
    assert food["initial_units"] == 27 and food["final_units"] == 82
    assert food["complete_measurements"] == food["observed_boundaries"] == 65
    assert food["unknown_measurements"] == 0
    assert food["historical_food_unknowns_preserved"] is True
    assert food["model_requests_remain_screen_only"] is True
    assert food["sustainability"] == "not_established"
    assert row["outcome_counts"]["food_stock"] is None
    assert row["outcome_counts"]["advancing_decisions"] == 11
    assert row["outcome_counts"]["zero_tick_decisions"] == 53
    assert row["execution_counts"] == {
        "requested_elapsed_ticks": 21200, "model_input_rejections": 0,
        "rejected_native_key_events": 0, "menu_deferrals": 0, "clock_unavailable_timeouts": 0,
    }
    assert row["teardown_verified"] is True
    assert row["final_checkpoint_fresh_reload_verified"] is False
    assert row["new_restart_performed"] is row["uninterrupted_campaign"] is False
    assert "operator_status" not in row and "operator_observation_warning" not in row
    assert parent["operator_status"] == "failed"
    events = [{"kind": "continuation", "id": item["continuation_id"]} for item in (parent, row)]
    offset = data["continuation_events"].index(events[0])
    assert data["continuation_events"][offset:offset + 2] == events


def test_next_food_window_preserves_condition_and_cumulative_budget():
    from fort_gym.bench.run.keyboard_config import load_window

    root = records.PROJECT_ROOT
    condition = root / "experiments/campaign_astra_keyboard_20260907.json"
    before, previous = load_window(condition, root / "experiments/campaign_astra_keyboard_window_20260908n.json")
    after, following = load_window(condition, root / "experiments/campaign_astra_keyboard_window_20260908o.json")
    assert before == after
    assert previous["continuation_from_next_step"] == 567
    assert following["continuation_from_next_step"] == 631
    for key in ("snapshot_profile", "private_measurement_profile", "steps_per_segment", "max_segments"):
        assert following[key] == previous[key]
    assert all(following[key] is False for key in ("reset_memory", "reset_usage", "strategy_intervention"))
    assert "budget_extension" not in following and "restart" not in following
