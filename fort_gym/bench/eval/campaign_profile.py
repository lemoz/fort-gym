"""Descriptive campaign outcomes, independent of frozen gates and scalar scores.

Consume one canonical trace, whose checkpoint prefix is already materialized by
CampaignLoop. Never concatenate ancestor traces or sum cumulative segment costs.
Stock changes are not production/consumption, acceptance is not completed work,
and a first anniversary is not proof of a functioning autonomous fortress.
"""

from __future__ import annotations

import json
from collections import Counter
from decimal import Decimal, InvalidOperation
from typing import Any

from .campaign import campaign_progress

METRICS = (
    "population",
    "food_stock",
    "drink_stock",
    "wood_stock",
    "stone_stock",
    "functional_rooms",
    "completed_workshops",
    "completed_beds",
    "completed_farms",
    "recorded_dead_citizens",
)
ACTION_TYPES = {"DIG", "BUILD", "ORDER", "UNSUSPEND", "FARM", "LABOR", "WAIT", "INTERACT"}


def count(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def mapping(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def metrics_from_state(value: Any) -> dict[str, int | None]:
    state = mapping(value)
    quality = mapping(state.get("campaign_observation_quality"))
    stocks = mapping(state.get("stocks"))
    validated = (
        quality.get("schema_version") == "fortgym.campaign-observation-quality/v1"
        and quality.get("native_population_resources_validated") is True
    )
    metrics: dict[str, int | None] = {name: None for name in METRICS}
    if validated:
        metrics["population"] = count(state.get("population"))
        for key in ("food", "drink", "wood", "stone"):
            metrics[f"{key}_stock"] = count(stocks.get(key))
    fort, crew = mapping(state.get("fort")), mapping(state.get("crew"))
    if (
        fort.get("ok") is True
        and fort.get("building_scan_complete") is True
        and fort.get("component_scan_truncated") is False
        and fort.get("spaces_truncated") is False
    ):
        metrics["functional_rooms"] = count(fort.get("functional_rooms"))
    if crew.get("ok") is True and crew.get("building_evidence_complete") is True:
        metrics["completed_beds"] = count(
            mapping(crew.get("placed_furniture_completed")).get("bed")
        )
        for name, key, truncated in (
            ("completed_workshops", "workshops", "workshops_truncated"),
            ("completed_farms", "farm_plot_details", "farm_plot_details_truncated"),
        ):
            entries = crew.get(key)
            if (
                isinstance(entries, list)
                and crew.get(truncated) is False
                and all(
                    isinstance(entry, dict)
                    and entry.get("stage_read_ok") is True
                    and type(entry.get("built")) is bool
                    for entry in entries
                )
            ):
                metrics[name] = sum(entry["built"] for entry in entries)
    if crew.get("ok") is True and crew.get("death_evidence_complete") is True:
        metrics["recorded_dead_citizens"] = count(crew.get("dead_citizen_count"))
    return metrics


def metric_summary(values: list[int | None]) -> dict:
    known = [value for value in values if value is not None]
    start, end = values[0], values[-1]
    return {
        "start": start,
        "end": end,
        "change": end - start if start is not None and end is not None else None,
        "minimum_observed": min(known) if known else None,
        "maximum_observed": max(known) if known else None,
        "observed_samples": len(known),
        "missing_samples": len(values) - len(known),
        "evidence": "complete" if len(known) == len(values) else "incomplete",
    }


def usage_profile(usage: Any) -> dict:
    usage = mapping(usage)
    fields = ("total_tokens", "dispatched_requests", "returned_responses", "accounted_responses")
    result: dict[str, Any] = {key: count(usage.get(key)) for key in fields}
    cost = usage.get("total_cost_usd")
    try:
        amount = Decimal(cost) if isinstance(cost, str) and cost.strip() else None
    except InvalidOperation:
        amount = None
    result["reported_model_cost_usd"] = (
        str(amount) if amount is not None and amount.is_finite() and amount >= 0 else None
    )
    dispatched, returned = result["dispatched_requests"], result["returned_responses"]
    result["dispatches_without_returned_usage"] = (
        dispatched - returned
        if dispatched is not None and returned is not None and dispatched >= returned
        else None
    )
    result["billing_reconciled"] = False
    if usage.get("cost_basis") == "self_hosted_no_metered_provider":
        result.update(
            cost_basis="self_hosted_no_metered_provider",
            reported_model_cost_usd=None,
            metered_provider_charge_usd="0"
            if amount == 0
            or ("total_cost_usd" not in usage and usage.get("metered_provider_charge_usd") == "0")
            else None,
            infrastructure_cost_usd=None,
        )
    return result


def campaign_profile(
    records: list[dict],
    *,
    campaign_id: str,
    status: str,
    usage: dict | None,
    terminal_state: dict | None,
    initial_state: dict | None = None,
) -> dict:
    """Describe observed boundaries, leaving unavailable terminal values unknown."""
    if any(row.get("run_id") != campaign_id for row in records):
        raise ValueError("Campaign profile cannot combine different trace identities")
    initial = records[0].get("observation") if records else initial_state
    boundaries = [initial, *(row.get("state_after_advance") for row in records)]
    # A failed final read is explicitly missing; don't reuse an older healthy
    # population or stockpile and describe it as the terminal observation.
    if terminal_state is None or boundaries[-1] != terminal_state:
        boundaries.append(terminal_state)
    points: list[dict[str, Any]] = [
        {
            "boundary_index": index,
            "year": count(mapping(state).get("year")),
            "year_tick": count(mapping(state).get("year_tick")),
            "metrics": metrics_from_state(state),
        }
        for index, state in enumerate(boundaries)
    ]
    totals: Counter[str] = Counter()
    mix: dict[str, Counter[str]] = {}
    previous_action = None
    previous_rejected = False
    changed_after_rejection = 0
    for row in records:
        action, execution = mapping(row.get("action")), mapping(row.get("execute"))
        supplied_kind = action.get("type")
        kind = (
            supplied_kind
            if isinstance(supplied_kind, str) and supplied_kind in ACTION_TYPES
            else "UNKNOWN"
        )
        accepted = execution.get("accepted")
        outcome = "accepted" if accepted is True else "rejected" if accepted is False else "unknown"
        totals[outcome] += 1
        if accepted is False and execution.get("why") == "path_cache_stale":
            totals["path_cache_stale_rejections"] += 1
        mix.setdefault(kind, Counter())[outcome] += 1
        command = json.dumps({"type": kind, "params": action.get("params")}, sort_keys=True)
        if previous_rejected and command != previous_action:
            changed_after_rejection += 1
        previous_action, previous_rejected = command, accepted is False
    known_statuses = {
        "bounded_segment_complete",
        "budget_limited_pause",
        "failed",
        "checkpoint_failed",
    }
    progress = campaign_progress(records)
    progress["scope"] = "committed_campaign_trace"
    issues = []
    if records and records[0].get("step") != 0:
        issues.append("missing_campaign_origin_step")
    calendar_keys = ("start_year", "start_tick", "end_year", "end_tick")
    if any(
        any(count(mapping(row.get("tick_advance")).get(key)) is None for key in calendar_keys)
        for row in records
    ):
        issues.append("missing_native_calendar")
    if issues:
        progress.update(
            time_evidence="incomplete",
            elapsed_ticks=None,
            elapsed_years=None,
            year_two_reached=None,
        )
    progress["profile_time_issues"] = issues
    return {
        "schema_version": "fortgym.campaign-profile/v1",
        "campaign_id": campaign_id,
        "scope": "canonical_campaign_trace",
        "segment_status": status if status in known_statuses else "unknown",
        "progress": progress,
        "metrics": {
            key: metric_summary([point["metrics"][key] for point in points]) for key in METRICS
        },
        "timeline": points,
        "actions": {
            "committed_rows": len(records),
            **{key: totals[key] for key in ("accepted", "rejected", "unknown")},
            "by_type": {
                key: {outcome: value[outcome] for outcome in ("accepted", "rejected", "unknown")}
                for key, value in sorted(mix.items())
            },
            "changed_command_after_rejection": changed_after_rejection,
            "path_cache_stale_rejections": totals["path_cache_stale_rejections"],
        },
        "usage": usage_profile(usage),
        "flow_measurement": {"status": "unavailable", "production": None, "consumption": None},
        "functioning_fortress": "not_assessed",
        "autonomous_gameplay": "not_assessed",
        "fortress_collapse": "not_assessed",
        "limits": [
            "Food and drink are native UI stock counters, not production or consumption measurements.",
            "Room and building counts are unknown when the source reports an incomplete or truncated scan.",
            "Recorded dead citizens includes the starting world's history; population changes do not identify death causes.",
            "Accepted commands and changed commands are observations, not completed-work or successful-adaptation verdicts.",
            "Metrics describe sampled boundaries; unseen between-sample extrema are not known.",
            "This canonical trace contains its checkpoint prefix. Do not add ancestor trace durations or cumulative costs.",
            "A budget pause or harness failure is not evidence of fortress collapse. Time alone is not autonomous success.",
        ],
    }
