"""Validate saved continuation lineage without reading private game state."""

import hashlib
import json
import re
from typing import Any

STORAGE_BINDING = "81b60b43fffdad75b1a3d9bdc7a3014a99e9890344dae532c4ba0406ed483779"


def encoded(value: dict) -> bytes:
    """Canonical public configuration encoding used for declaration digests."""
    return (json.dumps(value, indent=2, allow_nan=False) + "\n").encode()


def digest(value: dict) -> str:
    return hashlib.sha256(encoded(value)).hexdigest()


def same(left: Any, right: Any) -> bool:
    return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)


def count(value: Any) -> bool:
    return type(value) is int and 0 <= value <= 2**53 - 1


def exact_digest(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def totals(result: dict) -> tuple[int, int]:
    """Return cumulative responses and tokens for either public record schema."""
    if result["schema_version"] == "fortgym.public-matched-keyboard-result/v1":
        return result["responses"], result["usage"]["returned_tokens"]
    return result["next_decision"], result["usage"]["campaign_returned_tokens"]


def validate_continuation(result: dict, parent: dict, window: dict, condition: dict) -> None:
    """Require an exact own-save successor, including settled cumulative usage."""
    if not isinstance(result, dict):
        raise ValueError("A continuation must be a record object")
    cursor, tokens = totals(parent)
    limit = window["steps_per_segment"] * window["max_segments"]
    expected = {
        "schema_version": "fortgym.public-matched-keyboard-continuation/v1",
        "origin_kind": "saved_campaign_checkpoint",
        "start_decision": cursor,
        "response_limit": limit,
        "prior_checkpoint_sha256": parent["checkpoint_sha256"],
        "source_result_sha256": window["source_result_sha256"],
        "saved_elapsed_ticks_before_window": parent["saved_elapsed_ticks"],
        "initial_metrics": parent["saved_metrics"],
        "checkpoint_verified": True,
        "source_checkpoint_fresh_load_verified": True,
        "memory_preserved_at_start": True,
        "prompt_change": False,
        "budget_extension": False,
        "human_gameplay_rescue": False,
        "new_native_save_losses": 0,
        "native_cleanup_verified": True,
        "vm_teardown_verified": True,
    }
    for key in (
        "campaign_id",
        "cohort_id",
        "condition_id",
        "model",
        "replicate",
        "reasoning_effort",
        "control_profile",
        "observation_profile",
        "screen_size",
        "prompt_profile",
    ):
        expected[key] = parent[key]
    if any(not same(result.get(key), value) for key, value in expected.items()):
        raise ValueError("Continuation differs from its own saved parent or conditions")
    execution, prior = result["execution"], parent["execution"]
    if not isinstance(execution, dict):
        raise ValueError("Continuation execution must be explicit")
    if (
        any(
            execution.get(key) != prior[key]
            for key in (
                "source_revision",
                "image_id",
                "seed_receipt_sha256",
                "cohort_plan_sha256",
                "condition_file_sha256",
            )
        )
        or execution.get("window_sha256") != digest(window)
        or not same(execution.get("data_disk_gib"), 32)
        or not isinstance(execution.get("declaration_revision"), str)
        or re.fullmatch(r"[a-f0-9]{40}", execution["declaration_revision"]) is None
        or execution.get("binding_sha256") != STORAGE_BINDING
    ):
        raise ValueError("Continuation execution does not bind the reproduced window")
    for key in ("checkpoint_sha256", "audit_sha256"):
        if not exact_digest(result.get(key)):
            raise ValueError("An exact checkpoint and audit are required")
    if type(result.get("final_fresh_reload_verified")) is not bool:
        raise ValueError("Final reload proof must be explicit")
    if any(
        not count(result.get(key))
        for key in (
            "next_decision",
            "new_responses",
            "new_saved_ticks",
            "saved_elapsed_ticks",
        )
    ):
        raise ValueError("Invalid continuation counts")
    responses = result["new_responses"]
    if (
        responses > limit
        or result["next_decision"] != cursor + responses
        or result["next_decision"] > condition["max_dispatches"]
        or result["saved_elapsed_ticks"]
        != parent["saved_elapsed_ticks"] + result["new_saved_ticks"]
        or not same(result.get("year_two_reached"), result["saved_elapsed_ticks"] >= 403200)
        or (result.get("status"), result.get("stop_reason"))
        != (
            ("completed", "segment_limit")
            if responses == limit
            else ("paused", "budget_limited_pause")
        )
    ):
        raise ValueError("Continuation stop or cumulative clock does not reconcile")
    usage = result["usage"]
    if not isinstance(usage, dict):
        raise ValueError("Continuation usage must be explicit")
    if (
        not count(usage.get("new_returned_tokens"))
        or not count(usage.get("campaign_returned_tokens"))
        or not same(usage.get("returned_tokens_before_window"), tokens)
        or not same(usage.get("campaign_accounted_responses"), cursor + responses)
        or usage["campaign_returned_tokens"] != tokens + usage["new_returned_tokens"]
        or usage["campaign_returned_tokens"] > condition["max_total_tokens"]
        or (responses == 0) != (usage["new_returned_tokens"] == 0)
        or usage.get("reported_charge_usd", "missing") is not None
        or usage.get("cost_basis") != "codex_subscription_charge_unreported/v1"
    ):
        raise ValueError("Continuation usage is unsettled or changes its cost basis")
    _validate_observations(result, parent, responses)


def _validate_observations(result: dict, parent: dict, responses: int) -> None:
    def metrics(value: Any) -> bool:
        return (
            isinstance(value, dict)
            and value.keys() == parent["saved_metrics"].keys()
            and all(v is None or count(v) for v in value.values())
        )

    timeline = result["new_window_timeline"]
    if (
        not isinstance(timeline, list)
        or len(timeline) != responses
        or not metrics(result["saved_metrics"])
    ):
        raise ValueError("Missing saved continuation observations")
    previous = parent["saved_elapsed_ticks"]
    for decision, point in enumerate(timeline, start=totals(parent)[0] + 1):
        if (
            not isinstance(point, dict)
            or not same(point.get("decision"), decision)
            or not count(point.get("campaign_elapsed_ticks"))
            or not count(point.get("new_elapsed_ticks"))
            or point["campaign_elapsed_ticks"] < previous
            or point["campaign_elapsed_ticks"]
            != parent["saved_elapsed_ticks"] + point["new_elapsed_ticks"]
            or not metrics(point.get("metrics"))
            or point.get("accepted") is not None
            and type(point["accepted"]) is not bool
        ):
            raise ValueError("Continuation observations do not follow their own clock")
        previous = point["campaign_elapsed_ticks"]
    final_metrics = timeline[-1]["metrics"] if timeline else parent["saved_metrics"]
    outcomes = result["new_window_clock_outcomes"]
    if (
        previous != result["saved_elapsed_ticks"]
        or not same(final_metrics, result["saved_metrics"])
        or not isinstance(outcomes, dict)
        or not all(count(v) for v in outcomes.values())
        or sum(outcomes.values()) != responses
    ):
        raise ValueError("Final continuation outcome differs from its saved observations")
