"""Recorded continuation windows, separate from initial and live observations."""

import json
import re
from typing import Any

from .keyboard_cohort import PLAN_SHA256, STORAGE_BINDING, _link, _read, keyboard_cohort
from .keyboard_continuation_live import DECLARATION_REVISION, source_record

SCHEMA = "fortgym.public-keyboard-continuations/v1"
RESULTS = {
    "matched-20260910-astra-r1": (
        "experiments/evidence/keyboard_matched_astra_r1_continuation_32_64_20260910.json",
        "2c8abe1f7135d94ed27aea51e18ebc59e0599205caf3f268f4480b0e377f3d29",
        "ba66f1e4673cb5d66974693b9a094e61f4f7a150",
    ),
    "matched-20260910-sol-r1": (
        "experiments/evidence/keyboard_matched_sol_r1_continuation_32_64_20260910.json",
        "a624a9687257157aa91029d950ca1735a0e8f1baaa224cb66bba7efac50a1dbd",
        "52942d3669f6fb1c0d3dcb35dffb578c8ec5b734",
    ),
    "matched-20260910-terra-r1": (
        "experiments/evidence/keyboard_matched_terra_r1_continuation_32_64_20260910.json",
        "e81a20836eb6959a529b657a72339bca2e299203c73188006fb32d682c734e11",
        "a46836aabe58491f924f2e82ebddcbc09cf554a3",
    ),
}


def same(actual: Any, expected: Any) -> bool:
    return json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True)


def count(value: Any) -> bool:
    return type(value) is int and 0 <= value <= 2**53 - 1


def metrics(value: Any, keys: set[str]) -> bool:
    return (
        isinstance(value, dict)
        and value.keys() == keys
        and all(measurement is None or count(measurement) for measurement in value.values())
    )


def validate_result(result: dict, row: dict) -> None:
    """Bind the saved child to its own declared parent, budget and cumulative totals."""
    _, source, window, _ = source_record(row["campaign_id"])
    initial = row["result"]
    expected = {
        "schema_version": "fortgym.public-matched-keyboard-continuation/v1",
        "campaign_id": row["campaign_id"],
        "model": row["model"],
        "replicate": row["replicate"],
        "reasoning_effort": "medium",
        "cohort_id": initial["cohort_id"],
        "condition_id": initial["condition_id"],
        "origin_kind": "saved_campaign_checkpoint",
        "start_decision": source["cursor"],
        "response_limit": window["steps_per_segment"],
        "prior_checkpoint_sha256": source["checkpoint_sha256"],
        "source_result_sha256": source["public_result_sha256"],
        "saved_elapsed_ticks_before_window": source["saved_elapsed_ticks"],
        "initial_metrics": initial["saved_metrics"],
        "checkpoint_verified": True,
        "source_checkpoint_fresh_load_verified": True,
        "memory_preserved_at_start": True,
        "prompt_change": False,
        "budget_extension": False,
        "human_gameplay_rescue": False,
        "new_native_save_losses": 0,
        "native_cleanup_verified": True,
        "vm_teardown_verified": True,
        "sustainability_established": False,
        "functioning_fortress": "not_assessed",
        "matched_comparison_complete": False,
    }
    for key in ("control_profile", "observation_profile", "screen_size", "prompt_profile"):
        expected[key] = initial[key]
    execution = {
        **{
            key: initial["execution"][key]
            for key in (
                "source_revision",
                "image_id",
                "seed_receipt_sha256",
                "condition_file_sha256",
            )
        },
        "cohort_plan_sha256": PLAN_SHA256,
        "binding_sha256": STORAGE_BINDING,
        "window_sha256": source["declaration_sha256"],
        "declaration_revision": DECLARATION_REVISION,
        "data_disk_gib": 32,
    }
    if any(not same(result.get(key), value) for key, value in expected.items()) or not same(
        result.get("execution"), execution
    ):
        raise ValueError("Recorded continuation differs from its declared saved origin")
    for key in ("new_responses", "next_decision", "new_saved_ticks", "saved_elapsed_ticks"):
        if not count(result.get(key)):
            raise ValueError("Invalid saved continuation count")
    responses = result["new_responses"]
    if (
        not isinstance(result.get("checkpoint_sha256"), str)
        or re.fullmatch("[a-f0-9]{64}", result["checkpoint_sha256"]) is None
        or type(result.get("final_fresh_reload_verified")) is not bool
        or not same(result.get("year_two_reached"), result["saved_elapsed_ticks"] >= 403200)
        or not metrics(result.get("saved_metrics"), set(initial["saved_metrics"]))
    ):
        raise ValueError("Invalid final saved outcome")
    if (
        responses > window["steps_per_segment"]
        or result["next_decision"] != source["cursor"] + responses
        or result["saved_elapsed_ticks"]
        != source["saved_elapsed_ticks"] + result["new_saved_ticks"]
    ):
        raise ValueError("Saved continuation counts do not reconcile")
    if (result["status"], result["stop_reason"]) != (
        ("completed", "segment_limit")
        if responses == window["steps_per_segment"]
        else ("paused", "budget_limited_pause")
    ):
        raise ValueError("Window outcome does not match its bounded response count")
    usage = result["usage"]
    if (
        not count(usage.get("new_returned_tokens"))
        or not count(usage.get("campaign_returned_tokens"))
        or not same(usage.get("returned_tokens_before_window"), source["returned_tokens"])
        or not same(usage.get("campaign_accounted_responses"), source["cursor"] + responses)
        or usage["campaign_returned_tokens"]
        != source["returned_tokens"] + usage["new_returned_tokens"]
        or usage.get("reported_charge_usd", "missing") is not None
        or usage.get("cost_basis") != "codex_subscription_charge_unreported/v1"
    ):
        raise ValueError("Saved continuation usage does not reconcile")
    timeline = result["new_window_timeline"]
    if not isinstance(timeline, list) or len(timeline) != responses:
        raise ValueError("Missing saved decision observations")
    previous = source["saved_elapsed_ticks"]
    for decision, point in enumerate(timeline, start=source["cursor"] + 1):
        if (
            not same(point.get("decision"), decision)
            or not count(point.get("campaign_elapsed_ticks"))
            or not count(point.get("new_elapsed_ticks"))
            or point["campaign_elapsed_ticks"] < previous
            or point["campaign_elapsed_ticks"]
            != source["saved_elapsed_ticks"] + point["new_elapsed_ticks"]
            or not metrics(point.get("metrics"), set(initial["saved_metrics"]))
            or point.get("accepted") is not None
            and type(point["accepted"]) is not bool
        ):
            raise ValueError("Recorded continuation time is not cumulative")
        previous = point["campaign_elapsed_ticks"]
    if (
        previous != result["saved_elapsed_ticks"]
        or timeline
        and not same(timeline[-1]["metrics"], result["saved_metrics"])
    ):
        raise ValueError("Final saved observation differs from the recorded outcome")
    outcomes = result["new_window_clock_outcomes"]
    if (
        not isinstance(outcomes, dict)
        or not all(count(n) for n in outcomes.values())
        or sum(outcomes.values()) != responses
    ):
        raise ValueError("Clock outcome counts differ from the saved window")


def keyboard_continuations() -> dict:
    cohort = keyboard_cohort()
    trials = []
    for initial in cohort["trials"]:
        identity = initial["campaign_id"]
        row = {
            key: initial[key] for key in ("campaign_id", "model", "replicate", "reasoning_effort")
        }
        row.update(
            result=None,
            publication_state="no_published_result",
            evidence_url=None,
            evidence_sha256=None,
            initial_result_url=initial["evidence_url"],
        )
        if identity in RESULTS:
            path, digest, revision = RESULTS[identity]
            result = _read(path, digest)
            validate_result(result, initial)
            row.update(
                result=result,
                publication_state="recorded",
                evidence_url=_link(path, revision),
                evidence_sha256=digest,
            )
        trials.append(row)
    return {
        "schema_version": SCHEMA,
        "cohort_id": cohort["cohort_id"],
        "trials": trials,
        "recorded_windows": sum(row["result"] is not None for row in trials),
        "declared_windows": len(trials),
        "start_decision": 32,
        "end_decision": 64,
        "year_two_elapsed_ticks": cohort["year_two_elapsed_ticks"],
        "strong_ranking_supported": False,
        "live_owner_status_included": False,
        "limits": [
            "Only audited saved outcomes appear here. No published result means unknown, not a failed or inactive run.",
            "Each continuation resumes its own fortress and model memory. New progress and cumulative totals are separate.",
            "All continuations use 32 GiB storage. The original first-window storage difference remains part of campaign history; wall-clock speed is not compared.",
            "A completed window is not a completed campaign. Same-seed pilot results do not establish a model ranking or sustainable production.",
            "Food and drink are stock snapshots. Job samples are not completed production; subscription charges are unreported, not zero.",
        ],
    }
