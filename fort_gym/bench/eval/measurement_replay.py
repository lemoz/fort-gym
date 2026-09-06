"""Offline comparison of historical and current G7 measurement contracts."""

from __future__ import annotations

from math import isfinite
from typing import Any, Dict, Mapping, Sequence

from .gates import evaluate_g7
from .rubric import evaluate_trace_records, evaluate_trace_records_v2


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _integer_fact(value: Any, *, nonnegative: bool = False) -> int | None:
    """Parse an exact integer without truncating malformed numeric evidence."""

    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, float) and (not isfinite(value) or not value.is_integer()):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return None if nonnegative and parsed < 0 else parsed


def _coordinate(value: Any) -> tuple[int, int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    parsed = tuple(_integer_fact(item) for item in value)
    if any(item is None for item in parsed):
        return None
    return int(parsed[0]), int(parsed[1]), int(parsed[2])


def _numeric_fact(value: Any) -> int | None:
    return _integer_fact(value, nonnegative=True)


def historical_sensor_coverage(
    records: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Describe which v5 facts exist without synthesizing missing evidence."""

    partial_placement_coordinates: set[tuple[int, int, int]] = set()
    all_claimed_construction_coordinates: set[tuple[int, int, int]] = set()
    room_evidence_rows = 0
    output_attribution_rows = 0
    for record in records:
        action = _mapping(record.get("action"))
        params = _mapping(action.get("params"))
        execute = _mapping(record.get("execute"))
        result = _mapping(execute.get("result"))
        if action.get("type") == "BUILD" and params.get("kind") in {"Wall", "Floor"}:
            placed = _list(result.get("placed"))
            for entry in placed:
                coordinate = _coordinate(
                    [
                        _mapping(entry).get("x"),
                        _mapping(entry).get("y"),
                        _mapping(entry).get("z"),
                    ]
                )
                if coordinate is None:
                    continue
                all_claimed_construction_coordinates.add(coordinate)
                if result.get("partial") is True:
                    partial_placement_coordinates.add(coordinate)
        metrics = _mapping(record.get("metrics"))
        if metrics.get("governed_owned_room_evidence_complete") is True:
            room_evidence_rows += 1
        if metrics.get("governed_owned_output_attribution_scope"):
            output_attribution_rows += 1

    # V5 facts are final-state facts. A missing post-advance snapshot must not
    # be backfilled from the same row's pre-action observation/apply state.
    final_advance = records[-1].get("state_after_advance") if records else None
    final_state: Dict[str, Any] = (
        dict(final_advance) if isinstance(final_advance, Mapping) else {}
    )
    fort = _mapping(final_state.get("fort"))
    final_metrics = _mapping(records[-1].get("metrics")) if records else {}
    survival = _mapping(final_state.get("survival"))
    action_rows = [
        record for record in records if isinstance(record.get("action"), Mapping)
    ]
    trace_run_ids = {
        str(record.get("run_id")) for record in action_rows if record.get("run_id")
    }
    trace_run_scope_valid = bool(
        action_rows
        and len(trace_run_ids) == 1
        and all(record.get("run_id") for record in action_rows)
        and survival.get("run_id") in trace_run_ids
    )
    final_room_evidence = bool(
        final_metrics.get("governed_owned_room_evidence_complete") is True
        or final_metrics.get("governed_owned_layout_room_lower_bound_proven") is True
    )
    final_building_evidence = (
        final_metrics.get("governed_owned_building_evidence_complete") is True
    )
    final_output_evidence = bool(
        final_metrics.get("governed_owned_output_evidence_complete") is True
        or final_metrics.get("governed_owned_output_lower_bound_proven") is True
    )
    flow_fields = (
        "food_produced_in_run",
        "food_consumed_in_run",
        "drink_produced_in_run",
        "drink_consumed_in_run",
    )
    flow_values = [_numeric_fact(survival.get(field)) for field in flow_fields]
    final_flow_evidence = bool(
        survival.get("flow_evidence_complete") is True
        and all(field in survival for field in flow_fields)
        and all(value is not None for value in flow_values)
        and trace_run_scope_valid
    )
    deaths_in_run = _numeric_fact(survival.get("deaths_in_run"))
    neglect_deaths = _numeric_fact(survival.get("neglect_deaths"))
    final_death_evidence = bool(
        survival.get("death_evidence_complete") is True
        and trace_run_scope_valid
        and deaths_in_run is not None
        and (
            deaths_in_run == 0
            or (
                survival.get("death_causes_known") is True
                and neglect_deaths is not None
            )
        )
    )
    full_summary = _mapping(summary)
    summary_evidence = all(
        _numeric_fact(full_summary.get(field)) is not None
        for field in (
            "governed_owned_accessible_layout_rooms",
            "duration_ticks",
            "end_pop",
        )
    )
    observed_final_constructions = {
        coordinate
        for value in _list(fort.get("construction_tiles"))
        if (coordinate := _coordinate(value)) is not None
    }
    claimed_and_observed = all_claimed_construction_coordinates.intersection(
        observed_final_constructions
    )
    return {
        "rows": len(records),
        "v5_owned_room_evidence_rows": room_evidence_rows,
        "v5_owned_output_attribution_rows": output_attribution_rows,
        "claimed_construction_coordinates": len(all_claimed_construction_coordinates),
        "claimed_partial_placement_coordinates": len(partial_placement_coordinates),
        "claimed_constructions_observed_final": len(claimed_and_observed),
        "final_unique_construction_coordinates": len(observed_final_constructions),
        "final_global_spaces": len(_list(fort.get("spaces"))),
        "final_v5_sensor_status": {
            "room": final_room_evidence,
            "building": final_building_evidence,
            "output": final_output_evidence,
            "survival_flow": final_flow_evidence,
            "death": final_death_evidence,
            "full_summary": summary_evidence,
        },
        "v5_replay_complete": bool(
            records
            and final_room_evidence
            and final_building_evidence
            and final_output_evidence
            and final_flow_evidence
            and final_death_evidence
            and summary_evidence
        ),
        "missing_evidence_policy": "unknown_not_zero",
    }


def replay_measurements(
    records: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
) -> Dict[str, Any]:
    """Evaluate one trace under preserved v4 and calibration v5 contracts."""

    materialized = [dict(record) for record in records]
    summary_wrapper = _mapping(summary)
    nested_summary = _mapping(summary_wrapper.get("summary"))
    full_summary = nested_summary if nested_summary else summary_wrapper
    summary_source = "public_wrapper" if nested_summary else "raw_summary"
    coverage = historical_sensor_coverage(records, full_summary)
    counterfactual_v4 = evaluate_g7(records, full_summary, gate_version=4)
    counterfactual_v4_input_complete = "fort_functional_rooms" in full_summary
    if not counterfactual_v4_input_complete:
        criterion = counterfactual_v4.get("criteria", {}).get("functional_rooms")
        if isinstance(criterion, dict):
            criterion["status"] = "unknown"
            criterion["reason"] = (
                "counterfactual input lacks the raw persisted summary room count"
            )
        statuses = [
            item.get("status")
            for item in counterfactual_v4.get("criteria", {}).values()
            if isinstance(item, dict)
        ]
        counterfactual_v4["status"] = (
            "fail"
            if "fail" in statuses
            else "unknown"
            if "unknown" in statuses
            else "pass"
        )
    calibration_g7_v5 = evaluate_g7(records, full_summary, gate_version=5)
    behavior_v2 = evaluate_trace_records_v2(materialized)
    incomplete_reasons = [
        f"missing_final_sensor:{name}"
        for name, complete in coverage["final_v5_sensor_status"].items()
        if not complete
    ]
    if (
        summary_source == "public_wrapper"
        and not coverage["final_v5_sensor_status"]["full_summary"]
    ):
        incomplete_reasons.append("compact_summary")
    if calibration_g7_v5.get("evaluation_validity", {}).get("status") != "pass":
        incomplete_reasons.append("g7_validity_not_pass")
    if behavior_v2.get("unknown_domain_count") != 0:
        incomplete_reasons.append("unknown_behavior_domains")
    evaluation_complete = bool(
        coverage["v5_replay_complete"]
        and calibration_g7_v5.get("evaluation_validity", {}).get("status") == "pass"
        and behavior_v2.get("unknown_domain_count") == 0
    )
    return {
        "summary_source": summary_source,
        "summary_is_full_for_v5": coverage["final_v5_sensor_status"]["full_summary"],
        "counterfactual_g7_v4_input_complete": counterfactual_v4_input_complete,
        "counterfactual_g7_v4": counterfactual_v4,
        "historical_rubric_v1": evaluate_trace_records(materialized),
        "calibration_g7_v5": calibration_g7_v5,
        "calibration_behavior_v2": behavior_v2,
        "sensor_coverage": coverage,
        "comparison_status": (
            "complete" if evaluation_complete else "incomplete_or_invalid_evidence"
        ),
        "comparison_incomplete_reasons": sorted(set(incomplete_reasons)),
    }


__all__ = ["historical_sensor_coverage", "replay_measurements"]
