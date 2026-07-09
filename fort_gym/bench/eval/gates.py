"""Deterministic WDSLL gate evaluators over recorded run artifacts."""

from __future__ import annotations

from math import ceil
from typing import Any, Dict, Iterable, Mapping, Sequence

PASS = "pass"
FAIL = "fail"
UNKNOWN = "unknown"

G7_DURATION_TICKS = 403_200
G7_MIN_POPULATION = 15
G7_MIN_FUNCTIONAL_ROOMS = 3
G7_MIN_SCORE = 150.0
G7_MIN_RUBRIC = 70.0


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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
    calls = 0
    prompt_tokens = 0
    completion_tokens = 0
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
            if isinstance(input_data, Mapping) and input_data.get("model"):
                models.add(str(input_data["model"]))
            if isinstance(output_data, Mapping):
                prompt_tokens += _to_int(output_data.get("prompt_tokens"))
                completion_tokens += _to_int(output_data.get("completion_tokens"))
            calls += 1
    return {
        "models": sorted(models),
        "calls": calls,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
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
) -> Dict[str, Any]:
    """Evaluate the ratified G7 predicates without filling evidence gaps by inference."""

    rows = _action_rows(records)
    state = _last_state(records)
    metrics = _last_metrics(records)
    crew = state.get("crew") if isinstance(state.get("crew"), Mapping) else {}
    stocks = state.get("stocks") if isinstance(state.get("stocks"), Mapping) else {}
    survival = state.get("survival") if isinstance(state.get("survival"), Mapping) else {}
    trace_run_ids = {str(record.get("run_id")) for record in rows if record.get("run_id")}
    survival_run_scope_valid = bool(
        len(trace_run_ids) == 1 and survival.get("run_id") in trace_run_ids
    )
    usage = _model_usage(rows)

    screen_count = sum(_valid_screen_capture(record.get("screen_text")) for record in rows)
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
    )

    trace_duration = sum(
        max(0, _to_int((record.get("tick_advance") or {}).get("ticks_advanced")))
        for record in rows
        if isinstance(record.get("tick_advance"), Mapping)
    )
    summary_duration = _to_int(summary.get("duration_ticks"))
    duration_summary_consistent = summary_duration <= 0 or summary_duration == trace_duration
    if not duration_summary_consistent:
        duration_status = FAIL
        duration_reason = "summary duration disagrees with trace tick advancement"
    elif trace_duration >= G7_DURATION_TICKS:
        duration_status = PASS
        duration_reason = None
    else:
        duration_status = FAIL
        duration_reason = "trace does not contain the required tick advancement"

    food_produced = _latest_fact(state, metrics, "food_produced_in_run")
    food_consumed = _latest_fact(state, metrics, "food_consumed_in_run")
    drink_produced = _latest_fact(state, metrics, "drink_produced_in_run")
    drink_consumed = _latest_fact(state, metrics, "drink_consumed_in_run")
    flow_evidence_complete = _latest_fact(state, metrics, "flow_evidence_complete")
    flow_values = (food_produced, food_consumed, drink_produced, drink_consumed)
    if _to_int(stocks.get("drink")) <= 0:
        loop_status = FAIL
        loop_reason = "final drink stock is zero"
    elif flow_evidence_complete is not True or not survival_run_scope_valid:
        loop_status = UNKNOWN
        loop_reason = "run-scoped production/consumption evidence is incomplete"
    elif all(value is not None for value in flow_values):
        loop_status = (
            PASS
            if _to_int(food_produced) > _to_int(food_consumed)
            and _to_int(drink_produced) > _to_int(drink_consumed)
            else FAIL
        )
        loop_reason = None
    else:
        loop_status = UNKNOWN
        loop_reason = "trace lacks cumulative farm/brew production and consumption facts"

    deaths_in_run = _latest_fact(state, metrics, "deaths_in_run")
    end_dead = (
        _to_int(deaths_in_run)
        if deaths_in_run is not None
        else _to_int(metrics.get("dead", state.get("dead")))
    )
    neglect_deaths = _latest_fact(state, metrics, "neglect_deaths")
    death_causes_known = _latest_fact(state, metrics, "death_causes_known")
    death_evidence_complete = _latest_fact(state, metrics, "death_evidence_complete")
    if end_dead == 0 and death_evidence_complete is True and survival_run_scope_valid:
        death_status = PASS
        death_reason = None
    elif end_dead == 0:
        death_status = UNKNOWN
        death_reason = "run-scoped death evidence is incomplete"
    elif (
        death_evidence_complete is True
        and death_causes_known is True
        and neglect_deaths is not None
        and survival_run_scope_valid
    ):
        death_status = PASS if _to_int(neglect_deaths) == 0 else FAIL
        death_reason = None
    else:
        death_status = UNKNOWN
        death_reason = "one or more deaths lack recorded cause evidence"

    population = _to_int(summary.get("end_pop", state.get("population")))
    rooms = _to_int(summary.get("fort_functional_rooms", metrics.get("fort_functional_rooms")))
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
        "duration": _criterion(
            duration_status,
            observed={
                "trace_ticks": trace_duration,
                "summary_ticks": summary_duration,
                "summary_consistent": duration_summary_consistent,
            },
            required=f">={G7_DURATION_TICKS}",
            reason=duration_reason,
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
            PASS if population >= G7_MIN_POPULATION else FAIL,
            observed=population,
            required=f">={G7_MIN_POPULATION}",
        ),
        "functional_rooms": _criterion(
            PASS if rooms >= G7_MIN_FUNCTIONAL_ROOMS else FAIL,
            observed=rooms,
            required=f">={G7_MIN_FUNCTIONAL_ROOMS}",
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
            PASS if score_version == 3 and score >= G7_MIN_SCORE else FAIL,
            observed={"score": score, "score_version": score_version},
            required=f"score-v3 >={G7_MIN_SCORE}",
        ),
    }

    statuses = [criterion["status"] for criterion in criteria.values()]
    overall = FAIL if FAIL in statuses else UNKNOWN if UNKNOWN in statuses else PASS
    terminal = records[-1].get("stopped") or records[-1].get("terminal_reason") if records else None
    return {
        "gate": "G7",
        "gate_version": 1,
        "status": overall,
        "criteria": criteria,
        "terminal": terminal,
    }


__all__ = ["FAIL", "PASS", "UNKNOWN", "evaluate_g7"]
