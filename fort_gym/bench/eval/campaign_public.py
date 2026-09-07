"""Bounded public campaign projections, without raw game, model, or runtime text."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .campaign_profile import (
    ACTION_TYPES,
    FURNITURE_RECORDS,
    METRICS,
    count,
    mapping,
    usage_profile,
)

SCHEMA = "fortgym.public-campaign-state/v1"
STAT_FIELDS = (
    "start",
    "end",
    "minimum_observed",
    "maximum_observed",
    "observed_samples",
    "missing_samples",
)
STATUSES = {
    "started",
    "bounded_segment_complete",
    "budget_limited_pause",
    "inference_output_limited_pause",
    "failed",
    "checkpoint_failed",
}
LIFECYCLES = {"starting", "running", "awaiting_teardown", "finished"}
FAILURE_KINDS = {"model_action", "provider", "runtime", "checkpoint", "unclassified", "none"}
HEX = re.compile(r"[a-f0-9]+")
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}")


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(value: Any, length: int) -> str:
    if not isinstance(value, str) or len(value) != length or HEX.fullmatch(value) is None:
        raise ValueError("Invalid public campaign digest")
    return value


def _identity(value: Any) -> str:
    if not isinstance(value, str) or IDENTIFIER.fullmatch(value) is None:
        raise ValueError("Invalid public campaign identity")
    return value


def parse_update_time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Missing campaign update timestamp")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Campaign update timestamp must have a timezone")
    return parsed


def public_snapshot(value: dict) -> dict:
    """Reconstruct a bounded public shape at BOTH write and read boundaries."""
    if value.get("schema_version") != SCHEMA:
        raise ValueError("Unsupported public campaign snapshot")
    lifecycle, status = value.get("lifecycle"), value.get("segment_status")
    if not isinstance(lifecycle, str) or lifecycle not in LIFECYCLES:
        raise ValueError("Invalid campaign lifecycle")
    if not isinstance(status, str) or status not in STATUSES:
        raise ValueError("Invalid campaign segment status")
    result: dict[str, Any] = {
        "schema_version": SCHEMA,
        **{
            key: _identity(value.get(key))
            for key in ("campaign_id", "segment_id", "model", "condition_id")
        },
        "code_revision": _digest(value.get("code_revision"), 40),
        "configuration_sha256": _digest(value.get("configuration_sha256"), 64),
        "updated_at": parse_update_time(value.get("updated_at")).isoformat(),
        "lifecycle": lifecycle,
        "segment_status": status,
        "failure_kind": value.get("failure_kind")
        if isinstance(value.get("failure_kind"), str) and value["failure_kind"] in FAILURE_KINDS
        else "none",
        "committed_steps": count(value.get("committed_steps")),
        "elapsed_ticks": count(value.get("elapsed_ticks")),
        "current_metrics": {
            key: count(mapping(value.get("current_metrics")).get(key)) for key in METRICS
        },
        "current_furniture_item_records": {
            key: count(mapping(value.get("current_furniture_item_records")).get(key))
            for key in FURNITURE_RECORDS
        },
        "usage": usage_profile(value.get("usage")),
        "checkpoint_verified": value.get("checkpoint_verified") is True,
        "cleanup_verified": value.get("cleanup_verified")
        if type(value.get("cleanup_verified")) is bool
        else None,
        "functioning_fortress": "not_assessed",
        "autonomous_gameplay": "not_assessed",
        "fortress_collapse": "not_assessed",
        "comparison_rankings_available": False,
        "flow_measurement": "unavailable",
    }
    # usage_profile consumes the canonical usage key; public snapshots use a
    # descriptive name. Support revalidation without silently losing its value.
    cost = mapping(value.get("usage")).get("reported_model_cost_usd")
    if cost is not None:
        result["usage"] = usage_profile({**mapping(value["usage"]), "total_cost_usd": cost})
    summaries = mapping(value.get("metric_summaries"))
    result["metric_summaries"] = {}
    for key in METRICS:
        if key not in summaries:
            continue
        item = mapping(summaries[key])
        fields = {field: count(item.get(field)) for field in STAT_FIELDS}
        start, end = fields["start"], fields["end"]
        fields["change"] = end - start if start is not None and end is not None else None
        result["metric_summaries"][key] = fields
    furniture = mapping(value.get("furniture_item_record_summaries"))
    result["furniture_item_record_summaries"] = {}
    for key in FURNITURE_RECORDS:
        if key not in furniture:
            continue
        item = mapping(furniture[key])
        fields = {field: count(item.get(field)) for field in STAT_FIELDS}
        start, end = fields["start"], fields["end"]
        fields["change"] = end - start if start is not None and end is not None else None
        result["furniture_item_record_summaries"][key] = fields
    result["furniture_item_record_scope"] = {
        "source": "legacy job_metrics.goods IN_PLAY item records",
        "scan_completeness": "not_reported",
        "production_attribution": "unavailable",
        "ownership_and_accessibility": "not_reported",
    }
    timeline = value.get("timeline")
    if not isinstance(timeline, list):
        timeline = []
    sampled = len(timeline) > 128
    indices = (
        sorted({round(index * (len(timeline) - 1) / 127) for index in range(128)})
        if sampled
        else range(len(timeline))
    )
    result["timeline"] = [
        {
            "boundary_index": count(mapping(timeline[index]).get("boundary_index")),
            "year": count(mapping(timeline[index]).get("year")),
            "year_tick": count(mapping(timeline[index]).get("year_tick")),
            "metrics": {
                key: count(mapping(mapping(timeline[index]).get("metrics")).get(key))
                for key in METRICS
            },
            "furniture_item_records": {
                key: count(mapping(mapping(timeline[index]).get("furniture_item_records")).get(key))
                for key in FURNITURE_RECORDS
            },
        }
        for index in indices
    ]
    result["timeline_sampled"] = sampled or value.get("timeline_sampled") is True
    result["source_sha256"] = {
        key: _digest(digest, 64)
        for key, digest in mapping(value.get("source_sha256")).items()
        if key in {"campaign-segment.json", "result.json", "campaign/trace.jsonl"}
    }
    actions = mapping(value.get("actions"))
    result["actions"] = {
        key: count(actions.get(key))
        for key in (
            "committed_rows",
            "accepted",
            "rejected",
            "unknown",
            "changed_command_after_rejection",
            "path_cache_stale_rejections",
        )
    }
    result["actions"]["by_type"] = {
        kind: {key: count(mapping(stats).get(key)) for key in ("accepted", "rejected", "unknown")}
        for kind, stats in mapping(actions.get("by_type")).items()
        if kind in ACTION_TYPES | {"UNKNOWN"}
    }
    return result
