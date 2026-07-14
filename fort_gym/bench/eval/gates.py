"""Deterministic WDSLL gate evaluators over recorded run artifacts."""

from __future__ import annotations

from math import ceil, isfinite
from typing import Any, Dict, Iterable, Mapping, Sequence

from .scoring import SCORE_VERSION

PASS = "pass"
FAIL = "fail"
UNKNOWN = "unknown"

G7_LEGACY_DURATION_TICKS = 403_200
G7_LEGACY_MIN_POPULATION = 15
G7_MIN_FUNCTIONAL_ROOMS = 3
G7_LEGACY_MIN_SCORE = 150.0
G7_MIN_RUBRIC = 70.0
G7_LEGACY_GATE_VERSION = 3
G7_V4_GATE_VERSION = 4
G7_GATE_VERSION = 5
G7_INITIAL_COHORT = 7


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_float_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _state_from_record(record: Mapping[str, Any]) -> Mapping[str, Any]:
    observation = record.get("observation")
    after = record.get("state_after_advance")
    if isinstance(observation, Mapping) or isinstance(after, Mapping):
        merged = dict(observation) if isinstance(observation, Mapping) else {}
        if isinstance(after, Mapping):
            merged.update(after)
        return merged
    applied = record.get("state_after_apply")
    return applied if isinstance(applied, Mapping) else {}


def _criterion(
    status: str,
    *,
    observed: Any,
    required: Any,
    reason: str | None = None,
    evidence: Any = None,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "status": status,
        "observed": observed,
        "required": required,
    }
    if reason:
        result["reason"] = reason
    if evidence is not None:
        result["evidence"] = evidence
    return result


def _action_rows(records: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [record for record in records if isinstance(record.get("action"), Mapping)]


def _valid_screen_capture(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    lowered = value.strip().lower()
    return lowered not in {
        "(screen capture failed)",
        "(empty screen)",
        "no recorded df screen frame",
    }


def _last_state(records: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    for record in reversed(records):
        observation = record.get("observation")
        after = record.get("state_after_advance")
        if isinstance(observation, Mapping) or isinstance(after, Mapping):
            merged = dict(observation) if isinstance(observation, Mapping) else {}
            if isinstance(after, Mapping):
                merged.update(after)
            return merged
        applied = record.get("state_after_apply")
        if isinstance(applied, Mapping):
            return applied
    return {}


def _last_metrics(records: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    for record in reversed(records):
        value = record.get("metrics")
        if isinstance(value, Mapping):
            return value
    return {}


def _model_usage(rows: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    models: set[str] = set()
    resolved_models: set[str] = set()
    providers: set[str] = set()
    generation_ids: set[str] = set()
    calls = 0
    attempt_events = 0
    failed_attempt_events = 0
    calls_missing_cost = 0
    calls_missing_resolved_model = 0
    prompt_tokens = 0
    completion_tokens = 0
    cached_tokens = 0
    cache_write_tokens = 0
    reasoning_tokens = 0
    cost = 0.0
    generation_telemetry_unavailable = 0
    for record in rows:
        events = record.get("events")
        if not isinstance(events, list):
            continue
        for event in events:
            if (
                not isinstance(event, Mapping)
                or (event.get("type") or event.get("t")) != "tool_call"
            ):
                continue
            data = event.get("data")
            if (
                not isinstance(data, Mapping)
                or data.get("tool") != "openrouter.chat.completions.create"
            ):
                continue
            input_data = data.get("input")
            output_data = data.get("output")
            attempt_events += 1
            if isinstance(input_data, Mapping) and input_data.get("model"):
                models.add(str(input_data["model"]))
            if isinstance(output_data, Mapping):
                generation_id = output_data.get("generation_id")
                if not generation_id:
                    failed_attempt_events += 1
                    continue
                calls += 1
                prompt_tokens += _to_int(output_data.get("prompt_tokens"))
                completion_tokens += _to_int(output_data.get("completion_tokens"))
                cached_tokens += _to_int(output_data.get("cached_tokens"))
                cache_write_tokens += _to_int(output_data.get("cache_write_tokens"))
                reasoning_tokens += _to_int(output_data.get("reasoning_tokens"))
                if output_data.get("cost") is None:
                    calls_missing_cost += 1
                else:
                    cost += _to_float(output_data.get("cost"))
                if output_data.get("resolved_model"):
                    resolved_models.add(str(output_data["resolved_model"]))
                else:
                    calls_missing_resolved_model += 1
                generation_ids.add(str(generation_id))
                generation = output_data.get("generation")
                if isinstance(generation, Mapping):
                    if generation.get("provider_name"):
                        providers.add(str(generation["provider_name"]))
                    if generation.get("status") != "available":
                        generation_telemetry_unavailable += 1
                    generation_cost = generation.get("total_cost")
                    if generation_cost is not None and output_data.get("cost") is None:
                        cost += _to_float(generation_cost)
            else:
                failed_attempt_events += 1
    uncached_prompt_tokens = max(0, prompt_tokens - cached_tokens)
    return {
        "models": sorted(models),
        "resolved_models": sorted(resolved_models),
        "providers": sorted(providers),
        "generation_ids": sorted(generation_ids),
        "calls": calls,
        "attempt_events": attempt_events,
        "failed_attempt_events": failed_attempt_events,
        "calls_missing_cost": calls_missing_cost,
        "calls_missing_resolved_model": calls_missing_resolved_model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "cached_tokens": cached_tokens,
        "cache_write_tokens": cache_write_tokens,
        "uncached_prompt_tokens": uncached_prompt_tokens,
        "cache_read_rate": (
            round(cached_tokens / prompt_tokens, 6) if prompt_tokens > 0 else 0.0
        ),
        "reasoning_tokens": reasoning_tokens,
        "cost_usd": round(cost, 8),
        "generation_telemetry_unavailable": generation_telemetry_unavailable,
    }


def _latest_fact(
    state: Mapping[str, Any],
    metrics: Mapping[str, Any],
    key: str,
) -> Any:
    survival = state.get("survival")
    if isinstance(survival, Mapping) and key in survival:
        return survival.get(key)
    return metrics.get(key)


def evaluate_g7(
    records: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
    *,
    gate_version: int = G7_V4_GATE_VERSION,
) -> Dict[str, Any]:
    """Evaluate the ratified G7 predicates without filling evidence gaps by inference."""

    if gate_version not in {
        G7_LEGACY_GATE_VERSION,
        G7_V4_GATE_VERSION,
        G7_GATE_VERSION,
    }:
        raise ValueError(f"unsupported G7 gate version: {gate_version}")

    rows = _action_rows(records)
    if gate_version == G7_GATE_VERSION and rows:
        final_row = rows[-1]
        final_state_after_advance = final_row.get("state_after_advance")
        final_state_evidence_complete = isinstance(
            final_state_after_advance, Mapping
        )
        state = (
            final_state_after_advance
            if isinstance(final_state_after_advance, Mapping)
            else {}
        )
        final_metrics = final_row.get("metrics")
        metrics = final_metrics if isinstance(final_metrics, Mapping) else {}
    else:
        final_state_evidence_complete = True
        state = _last_state(records)
        metrics = _last_metrics(records)
    crew = state.get("crew") if isinstance(state.get("crew"), Mapping) else {}
    stocks = state.get("stocks") if isinstance(state.get("stocks"), Mapping) else {}
    survival = (
        state.get("survival") if isinstance(state.get("survival"), Mapping) else {}
    )
    trace_run_ids = {
        record.get("run_id")
        for record in rows
        if isinstance(record.get("run_id"), str) and record.get("run_id")
    }
    trace_run_binding_complete = bool(
        rows
        and all(
            isinstance(record.get("run_id"), str) and record.get("run_id")
            for record in rows
        )
        and len(trace_run_ids) == 1
    )
    survival_run_scope_valid = bool(
        trace_run_binding_complete and survival.get("run_id") in trace_run_ids
    )
    usage = _model_usage(rows)

    screen_count = sum(
        _valid_screen_capture(record.get("screen_text")) for record in rows
    )
    proof_count = sum(
        isinstance(record.get("gameplay_proof"), Mapping)
        and record["gameplay_proof"].get("source") == "dfhack-map-and-state"
        and record["gameplay_proof"].get("provenance") == "dfhack_governed"
        for record in rows
    )
    governed_count = sum(
        isinstance(record.get("execute"), Mapping)
        and record["execute"].get("provenance") == "dfhack_governed"
        for record in rows
    )
    evidence_ok = bool(rows) and (
        screen_count == len(rows)
        and proof_count == len(rows)
        and governed_count == len(rows)
        and usage["calls"] > 0
        and len(usage["models"]) == 1
        and (
            gate_version != G7_GATE_VERSION
            or trace_run_binding_complete and final_state_evidence_complete
        )
    )

    parsed_tick_advances: list[int] = []
    trace_duration_complete = bool(rows)
    for record in rows:
        tick_advance = record.get("tick_advance")
        ticks_advanced = (
            _to_int_or_none(tick_advance.get("ticks_advanced"))
            if isinstance(tick_advance, Mapping)
            else None
        )
        if ticks_advanced is None:
            trace_duration_complete = False
        else:
            parsed_tick_advances.append(ticks_advanced)
    trace_duration = sum(parsed_tick_advances) if trace_duration_complete else None
    summary_duration = _to_int_or_none(summary.get("duration_ticks"))
    duration_evidence_available = bool(
        trace_duration is not None and summary_duration is not None
    )
    duration_summary_consistent = bool(
        duration_evidence_available
        and (summary_duration <= 0 or summary_duration == trace_duration)
    )
    if not duration_evidence_available:
        duration_reason = "duration diagnostic input is missing or malformed"
    elif not duration_summary_consistent:
        duration_reason = "summary duration disagrees with trace tick advancement"
    else:
        duration_reason = None
    duration_diagnostic = {
        "status": (
            "unavailable"
            if not duration_evidence_available
            else "consistent"
            if duration_summary_consistent
            else "inconsistent"
        ),
        "observed": {
            "trace_ticks": trace_duration,
            "summary_ticks": summary_duration,
            "summary_consistent": (
                duration_summary_consistent if duration_evidence_available else None
            ),
        },
        "gate_effect": "none",
        "note": "Elapsed ticks are recorded for analysis only and do not affect G7 status.",
    }
    if duration_reason:
        duration_diagnostic["reason"] = duration_reason

    food_produced = _latest_fact(state, metrics, "food_produced_in_run")
    food_consumed = _latest_fact(state, metrics, "food_consumed_in_run")
    drink_produced = _latest_fact(state, metrics, "drink_produced_in_run")
    drink_consumed = _latest_fact(state, metrics, "drink_consumed_in_run")
    flow_evidence_complete = _latest_fact(state, metrics, "flow_evidence_complete")
    flow_values = (food_produced, food_consumed, drink_produced, drink_consumed)
    if gate_version != G7_GATE_VERSION and _to_int(stocks.get("drink")) <= 0:
        loop_status = FAIL
        loop_reason = "final drink stock is zero"
    elif flow_evidence_complete is not True or not survival_run_scope_valid:
        loop_status = UNKNOWN
        loop_reason = "run-scoped production/consumption evidence is incomplete"
    elif all(value is not None for value in flow_values):
        positive_flows = bool(
            _to_int(food_produced) > _to_int(food_consumed)
            and _to_int(drink_produced) > _to_int(drink_consumed)
        )
        loop_status = PASS if positive_flows else FAIL
        loop_reason = None
    else:
        loop_status = UNKNOWN
        loop_reason = (
            "trace lacks cumulative farm/brew production and consumption facts"
        )

    deaths_in_run = _latest_fact(state, metrics, "deaths_in_run")
    death_count_value = (
        deaths_in_run
        if deaths_in_run is not None or gate_version == G7_GATE_VERSION
        else metrics.get("dead", state.get("dead"))
    )
    end_dead = _to_int_or_none(death_count_value)
    neglect_deaths = _latest_fact(state, metrics, "neglect_deaths")
    neglect_deaths_count = _to_int_or_none(neglect_deaths)
    death_causes_known = _latest_fact(state, metrics, "death_causes_known")
    death_evidence_complete = _latest_fact(state, metrics, "death_evidence_complete")
    death_records = survival.get("death_records")
    death_record_unit_ids = (
        [_to_int_or_none(record.get("unit_id")) for record in death_records]
        if isinstance(death_records, list)
        and all(isinstance(record, Mapping) for record in death_records)
        else []
    )
    death_record_cause_enums = (
        [_to_int_or_none(record.get("cause_enum")) for record in death_records]
        if isinstance(death_records, list)
        and all(isinstance(record, Mapping) for record in death_records)
        else []
    )
    death_records_complete = bool(
        gate_version != G7_GATE_VERSION
        or (
            end_dead == 0
            and isinstance(death_records, list)
            and len(death_records) == 0
        )
        or (
            isinstance(death_records, list)
            and end_dead is not None
            and len(death_records) == end_dead
            and all(unit_id is not None for unit_id in death_record_unit_ids)
            and len(set(death_record_unit_ids)) == len(death_record_unit_ids)
            and all(cause is not None for cause in death_record_cause_enums)
            and all(
                isinstance(record, Mapping)
                and record.get("cause_known") is True
                and isinstance(record.get("cause_name"), str)
                and bool(record.get("cause_name"))
                and record.get("cause_name") != "NONE"
                and record.get("cause_source")
                in {
                    "counters.death_cause",
                    "world.incidents.all[death_id].death_cause",
                }
                and (
                    record.get("cause_source") == "counters.death_cause"
                    or _to_int_or_none(record.get("incident_id")) is not None
                )
                for record in death_records
            )
        )
    )
    direct_neglect_death_count = (
        sum(
            record.get("cause_name") in {"HUNGER", "THIRST"}
            for record in death_records
            if isinstance(record, Mapping)
        )
        if death_records_complete and isinstance(death_records, list)
        else None
    )
    death_aggregate_contradictory = bool(
        end_dead is not None
        and neglect_deaths_count is not None
        and (
            neglect_deaths_count > end_dead
            or direct_neglect_death_count is not None
            and neglect_deaths_count != direct_neglect_death_count
        )
    )
    if end_dead is None:
        death_status = UNKNOWN
        death_reason = "run-scoped death count is missing or malformed"
    elif death_aggregate_contradictory:
        death_status = UNKNOWN
        death_reason = (
            "neglect death count exceeds the run-scoped death count"
            if neglect_deaths_count is not None
            and neglect_deaths_count > end_dead
            else "neglect death count disagrees with authoritative death records"
        )
    elif (
        end_dead == 0
        and death_evidence_complete is True
        and death_records_complete
        and survival_run_scope_valid
    ):
        death_status = PASS
        death_reason = None
    elif end_dead == 0:
        death_status = UNKNOWN
        death_reason = "run-scoped death evidence is incomplete"
    elif (
        death_evidence_complete is True
        and death_causes_known is True
        and death_records_complete
        and neglect_deaths_count is not None
        and survival_run_scope_valid
    ):
        death_status = PASS if neglect_deaths_count == 0 else FAIL
        death_reason = None
    else:
        death_status = UNKNOWN
        death_reason = "one or more deaths lack recorded cause evidence"

    population_raw = summary.get("end_pop", state.get("population"))
    population_fact = _to_int_or_none(population_raw)
    population = _to_int(population_raw)
    peak_population_raw = summary.get("peak_pop", population_fact)
    peak_population_fact = _to_int_or_none(peak_population_raw)
    population_diagnostic = {
        "status": (
            "recorded"
            if population_fact is not None and peak_population_fact is not None
            else "unavailable"
        ),
        "observed": {
            "end_population": population_fact,
            "peak_population": peak_population_fact,
            "deaths_in_run": deaths_in_run,
        },
        "gate_effect": "none",
        "note": (
            "Absolute population depends on stochastic migrant exposure. "
            "G7 records it for matched-cohort analysis but does not use it as a "
            "per-run pass/fail threshold."
        ),
    }
    trace_rooms_value = metrics.get("fort_functional_rooms")
    trace_rooms = _to_int(trace_rooms_value) if trace_rooms_value is not None else None
    summary_rooms_value = summary.get("fort_functional_rooms")
    summary_rooms = (
        _to_int(summary_rooms_value) if summary_rooms_value is not None else None
    )
    fort_metrics_observed = metrics.get("fort_metrics_observed")
    rooms_summary_consistent = (
        trace_rooms is not None
        and summary_rooms is not None
        and trace_rooms == summary_rooms
    )
    if fort_metrics_observed is not True or trace_rooms is None:
        room_status = UNKNOWN
        room_reason = "final trace lacks an attested fort structure observation"
    elif not rooms_summary_consistent:
        room_status = FAIL
        room_reason = "summary room count disagrees with final trace observation"
    else:
        room_status = PASS if trace_rooms >= G7_MIN_FUNCTIONAL_ROOMS else FAIL
        room_reason = None
    required_beds = ceil(population / 3) if population > 0 else 0
    completed_furniture = crew.get("placed_furniture_completed")
    completed_beds = (
        _to_int(completed_furniture.get("bed"))
        if isinstance(completed_furniture, Mapping)
        else None
    )

    rubric = summary.get("rubric") if isinstance(summary.get("rubric"), Mapping) else {}
    rubric_score = _to_float(rubric.get("rubric_score"))
    blockers = list(rubric.get("blockers") or [])
    score = _to_float(summary.get("total_score"))
    score_version = _to_int(summary.get("score_version"), default=1)
    score_fact = _to_float_or_none(summary.get("total_score"))
    score_version_fact = _to_int_or_none(summary.get("score_version"))
    population_score_fact = _to_float_or_none(summary.get("population_score"))
    scalar_score_diagnostic = {
        "status": (
            "recorded"
            if score_fact is not None and score_version_fact is not None
            else "unavailable"
        ),
        "observed": {
            "score": score_fact,
            "score_version": score_version_fact,
            "population_component": population_score_fact,
        },
        "gate_effect": "none",
        "note": (
            "Score-v5 includes a peak-population component. G7 records the "
            "scalar score for matched-cohort analysis but does not use it as a "
            "per-run pass/fail threshold."
        ),
    }

    if gate_version == G7_GATE_VERSION:
        owned_trace_rooms_value = metrics.get("governed_owned_accessible_layout_rooms")
        owned_trace_rooms = _to_int_or_none(owned_trace_rooms_value)
        owned_summary_rooms_value = summary.get(
            "governed_owned_accessible_layout_rooms"
        )
        owned_summary_rooms = _to_int_or_none(owned_summary_rooms_value)
        owned_room_evidence_complete = (
            metrics.get("governed_owned_room_evidence_complete") is True
        )
        owned_room_lower_bound_proven = (
            metrics.get("governed_owned_layout_room_lower_bound_proven") is True
        )
        owned_rooms_consistent = bool(
            owned_trace_rooms is not None
            and owned_summary_rooms is not None
            and owned_trace_rooms == owned_summary_rooms
        )
        owned_rooms_contradictory = bool(
            owned_trace_rooms is not None
            and owned_summary_rooms is not None
            and owned_trace_rooms != owned_summary_rooms
        )
        if owned_trace_rooms is None:
            owned_room_status = UNKNOWN
            owned_room_reason = "final trace lacks complete owned room geometry and accessibility evidence"
        elif not owned_rooms_consistent:
            owned_room_status = UNKNOWN
            owned_room_reason = (
                "owned room summary disagrees with final trace; evaluation is invalid"
            )
        elif (
            owned_trace_rooms >= G7_MIN_FUNCTIONAL_ROOMS
            and owned_room_lower_bound_proven
        ):
            owned_room_status = PASS
            owned_room_reason = None
        elif owned_room_evidence_complete:
            owned_room_status = (
                PASS if owned_trace_rooms >= G7_MIN_FUNCTIONAL_ROOMS else FAIL
            )
            owned_room_reason = None
        else:
            owned_room_status = UNKNOWN
            owned_room_reason = (
                "room scan was truncated before the required lower bound was proven"
            )

        owned_building_evidence_complete = (
            metrics.get("governed_owned_building_evidence_complete") is True
        )
        owned_beds_value = metrics.get("governed_owned_completed_beds")
        owned_beds = (
            _to_int_or_none(owned_beds_value)
            if owned_building_evidence_complete
            else None
        )
        owned_farms = (
            _to_int_or_none(metrics.get("governed_owned_completed_farm_plots"))
            if owned_building_evidence_complete
            else None
        )
        owned_stills = (
            _to_int_or_none(metrics.get("governed_owned_completed_stills"))
            if owned_building_evidence_complete
            else None
        )
        operational_farms = (
            _to_int_or_none(metrics.get("governed_owned_operational_farm_plots"))
            if owned_building_evidence_complete
            and metrics.get("governed_owned_operational_farm_evidence_complete")
            is True
            else None
        )
        operational_farm_evidence_complete = (
            metrics.get("governed_owned_operational_farm_evidence_complete") is True
        )
        output_by_job = metrics.get("governed_owned_output_units_by_job")
        output_evidence_complete = (
            metrics.get("governed_owned_output_evidence_complete") is True
        )
        output_lower_bound_proven = (
            metrics.get("governed_owned_output_lower_bound_proven") is True
        )
        if (
            not (output_evidence_complete or output_lower_bound_proven)
            or not isinstance(output_by_job, Mapping)
        ):
            owned_brew_units = None
        elif "brew" not in output_by_job:
            owned_brew_units = 0
        else:
            owned_brew_units = _to_int_or_none(output_by_job.get("brew"))
        final_food = _to_int_or_none(stocks.get("food"))
        final_drink = _to_int_or_none(stocks.get("drink"))
        stock_evidence_complete = final_food is not None and final_drink is not None
        if not owned_building_evidence_complete:
            provisioning_status = UNKNOWN
            provisioning_reason = "trace lacks exact owned production-building evidence"
        elif owned_farms is None or owned_stills is None or operational_farms is None:
            provisioning_status = UNKNOWN
            provisioning_reason = (
                "trace omits one or more exact owned provisioning facts"
            )
        elif owned_farms < 1 or operational_farms < 1 or owned_stills < 1:
            provisioning_status = FAIL
            provisioning_reason = None
        elif owned_brew_units is None:
            provisioning_status = UNKNOWN
            provisioning_reason = (
                "exact governed brew-output lifecycle evidence is incomplete"
            )
        else:
            provisioning_status = PASS if owned_brew_units >= 1 else FAIL
            provisioning_reason = None
        required_initial_cohort_beds = ceil(G7_INITIAL_COHORT / 3)
        gameplay_criteria = {
            "owned_operational_provisioning": _criterion(
                provisioning_status,
                observed={
                    "final_food": final_food,
                    "final_drink": final_drink,
                    "owned_completed_farm_plots": owned_farms,
                    "owned_completed_stills": owned_stills,
                    "owned_operational_farm_plots": operational_farms,
                    "owned_operational_farm_evidence_complete": (
                        operational_farm_evidence_complete
                    ),
                    "owned_brew_output_units": owned_brew_units,
                    "owned_output_evidence_complete": output_evidence_complete,
                    "owned_output_lower_bound_proven": output_lower_bound_proven,
                    "food_produced_in_run": food_produced,
                    "food_consumed_in_run": food_consumed,
                    "drink_produced_in_run": drink_produced,
                    "drink_consumed_in_run": drink_consumed,
                    "flow_evidence_complete": flow_evidence_complete,
                    "run_scope_valid": survival_run_scope_valid,
                },
                required=(
                    ">=1 exact owned operational crop-assigned farm, >=1 exact owned "
                    "completed still, and >=1 exact governed completed brew output; "
                    "stocks and cumulative flows are diagnostic only"
                ),
                reason=provisioning_reason,
            ),
            "neglect_deaths": _criterion(
                death_status,
                observed={
                    "dead": end_dead,
                    "deaths_in_run": deaths_in_run,
                    "death_evidence_complete": death_evidence_complete,
                    "death_causes_known": death_causes_known,
                    "death_records_complete": death_records_complete,
                    "direct_neglect_deaths_from_records": (
                        direct_neglect_death_count
                    ),
                    "neglect_deaths": neglect_deaths,
                    "run_scope_valid": survival_run_scope_valid,
                },
                required="zero authoritatively classified preventable deaths",
                reason=death_reason,
            ),
            "owned_accessible_layout_rooms": _criterion(
                owned_room_status,
                observed={
                    "trace_rooms": owned_trace_rooms,
                    "summary_rooms": owned_summary_rooms,
                    "summary_consistent": owned_rooms_consistent,
                    "evidence_complete": owned_room_evidence_complete,
                    "lower_bound_proven": owned_room_lower_bound_proven,
                    "owned_unique_construction_tiles": metrics.get(
                        "governed_owned_unique_construction_tiles"
                    ),
                },
                required=f">={G7_MIN_FUNCTIONAL_ROOMS} final owned accessible rooms",
                reason=owned_room_reason,
            ),
            "initial_cohort_bed_capacity": _criterion(
                UNKNOWN
                if owned_beds is None
                else PASS
                if owned_beds >= required_initial_cohort_beds
                else FAIL,
                observed={
                    "owned_completed_beds": owned_beds,
                    "initial_cohort": G7_INITIAL_COHORT,
                    "peak_population_diagnostic": peak_population_fact,
                },
                required=f">={required_initial_cohort_beds} exact owned completed beds",
                reason=(
                    "trace lacks exact owned completed furniture evidence"
                    if owned_beds is None
                    else None
                ),
            ),
        }
        gameplay_statuses = [
            criterion["status"] for criterion in gameplay_criteria.values()
        ]
        gameplay_outcome = (
            FAIL
            if FAIL in gameplay_statuses
            else UNKNOWN
            if UNKNOWN in gameplay_statuses
            else PASS
        )
        contradictory_evidence = (
            owned_room_evidence_complete and owned_rooms_contradictory
        ) or death_aggregate_contradictory
        if contradictory_evidence:
            validity_status = FAIL
        elif (
            not evidence_ok
            or not (
                owned_room_evidence_complete
                or owned_room_status == PASS
                and owned_room_lower_bound_proven
            )
            or not owned_building_evidence_complete
            or provisioning_status == UNKNOWN
            or UNKNOWN in gameplay_statuses
        ):
            validity_status = UNKNOWN
        else:
            validity_status = PASS
        terminal = (
            records[-1].get("stopped") or records[-1].get("terminal_reason")
            if records
            else None
        )
        return {
            "gate": "G7",
            "gate_version": gate_version,
            "status": gameplay_outcome if validity_status == PASS else UNKNOWN,
            "gameplay_outcome": {
                "status": gameplay_outcome,
                "criteria": gameplay_criteria,
            },
            "evaluation_validity": {
                "status": validity_status,
                "evidence_complete": evidence_ok,
                "final_state_evidence_complete": final_state_evidence_complete,
                "duration_evidence_available": duration_evidence_available,
                "duration_consistent": (
                    duration_summary_consistent
                    if duration_evidence_available
                    else None
                ),
                "owned_room_evidence_complete": owned_room_evidence_complete,
                "owned_room_lower_bound_proven": owned_room_lower_bound_proven,
                "owned_room_summary_consistent": owned_rooms_consistent,
                "owned_building_evidence_complete": owned_building_evidence_complete,
                "stock_evidence_complete": stock_evidence_complete,
            },
            "provenance_completeness": {
                "status": PASS if evidence_ok else UNKNOWN,
                "observed": {
                    "gameplay_rows": len(rows),
                    "screen_text": screen_count,
                    "gameplay_proof": proof_count,
                    "governed_provenance": governed_count,
                    "model_usage": usage,
                    "trace_run_binding_complete": trace_run_binding_complete,
                    "final_state_evidence_complete": final_state_evidence_complete,
                },
            },
            "criteria": gameplay_criteria,
            "diagnostics": {
                "duration": duration_diagnostic,
                "population": population_diagnostic,
                "scalar_score": scalar_score_diagnostic,
                "behavior": rubric,
            },
            "terminal": terminal,
        }

    criteria = {
        "evidence": _criterion(
            PASS if evidence_ok else FAIL,
            observed={
                "gameplay_rows": len(rows),
                "screen_text": screen_count,
                "gameplay_proof": proof_count,
                "governed_provenance": governed_count,
                "model_usage": usage,
            },
            required="complete evidence, governed provenance, one trace-attributed model",
        ),
        "food_and_drink_loop": _criterion(
            loop_status,
            observed={
                "final_food": _to_int(stocks.get("food")),
                "final_drink": _to_int(stocks.get("drink")),
                "food_produced_in_run": food_produced,
                "food_consumed_in_run": food_consumed,
                "drink_produced_in_run": drink_produced,
                "drink_consumed_in_run": drink_consumed,
                "flow_evidence_complete": flow_evidence_complete,
                "run_scope_valid": survival_run_scope_valid,
            },
            required="food produced > consumed and drink produced > consumed",
            reason=loop_reason,
        ),
        "neglect_deaths": _criterion(
            death_status,
            observed={
                "dead": end_dead,
                "deaths_in_run": deaths_in_run,
                "death_evidence_complete": death_evidence_complete,
                "death_causes_known": death_causes_known,
                "neglect_deaths": neglect_deaths,
                "run_scope_valid": survival_run_scope_valid,
            },
            required="zero starvation, dehydration, or tantrum-spiral deaths",
            reason=death_reason,
        ),
        "population": _criterion(
            PASS if population >= G7_LEGACY_MIN_POPULATION else FAIL,
            observed=population,
            required=f">={G7_LEGACY_MIN_POPULATION}",
        ),
        "functional_rooms": _criterion(
            room_status,
            observed={
                "trace_rooms": trace_rooms,
                "summary_rooms": summary_rooms,
                "summary_consistent": rooms_summary_consistent,
                "fort_metrics_observed": fort_metrics_observed,
            },
            required=f">={G7_MIN_FUNCTIONAL_ROOMS}",
            reason=room_reason,
        ),
        "installed_beds": _criterion(
            UNKNOWN
            if completed_beds is None
            else PASS
            if completed_beds >= required_beds
            else FAIL,
            observed=completed_beds,
            required=f">={required_beds} completed installations",
            reason=(
                "trace lacks placed_furniture_completed; placed_furniture includes pending jobs"
                if completed_beds is None
                else None
            ),
        ),
        "rubric": _criterion(
            PASS if rubric_score >= G7_MIN_RUBRIC and not blockers else FAIL,
            observed={"score": rubric_score, "blockers": blockers},
            required=f">={G7_MIN_RUBRIC} with zero blockers",
        ),
        "scalar_score": _criterion(
            PASS
            if score_version == SCORE_VERSION and score >= G7_LEGACY_MIN_SCORE
            else FAIL,
            observed={"score": score, "score_version": score_version},
            required=f"score-v{SCORE_VERSION} >={G7_LEGACY_MIN_SCORE}",
        ),
    }

    if gate_version == G7_V4_GATE_VERSION:
        criteria.pop("population")
        criteria.pop("scalar_score")

    if gate_version == G7_LEGACY_GATE_VERSION:
        if not duration_summary_consistent:
            legacy_duration_status = FAIL
        elif trace_duration >= G7_LEGACY_DURATION_TICKS:
            legacy_duration_status = PASS
        else:
            legacy_duration_status = FAIL
            duration_reason = "trace does not contain the required tick advancement"
        criteria = {
            "evidence": criteria.pop("evidence"),
            "duration": _criterion(
                legacy_duration_status,
                observed=duration_diagnostic["observed"],
                required=f">={G7_LEGACY_DURATION_TICKS}",
                reason=duration_reason,
            ),
            **criteria,
        }

    statuses = [criterion["status"] for criterion in criteria.values()]
    overall = FAIL if FAIL in statuses else UNKNOWN if UNKNOWN in statuses else PASS
    terminal = (
        records[-1].get("stopped") or records[-1].get("terminal_reason")
        if records
        else None
    )
    return {
        "gate": "G7",
        "gate_version": gate_version,
        "status": overall,
        "criteria": criteria,
        "diagnostics": (
            {
                "duration": duration_diagnostic,
                "population": population_diagnostic,
                "scalar_score": scalar_score_diagnostic,
            }
            if gate_version == G7_V4_GATE_VERSION
            else {}
        ),
        "terminal": terminal,
    }


__all__ = ["FAIL", "PASS", "UNKNOWN", "_model_usage", "evaluate_g7"]
