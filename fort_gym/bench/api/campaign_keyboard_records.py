"""Public operational milestones, explicitly separate from private game traces."""

from __future__ import annotations

import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PUBLISHED = (
    "astra_native_keyboard_outcomes_20260907.json",
    "astra_native_keyboard_endurance_20260907.json",
)
INTERRUPTIONS = (
    "astra_native_keyboard_interruption_20260907.json",
    "astra_native_keyboard_rejection_20260907.json",
)
RECOVERIES = (
    "astra_native_keyboard_recovery_20260907.json",
    "astra_native_keyboard_rejection_recovery_20260907.json",
)
PROGRESS_FIELDS = (
    "model_decisions",
    "native_key_events_confirmed",
    "elapsed_native_ticks",
    "cumulative_tokens",
    "checkpoint_cursors",
)


def _interruption(root: Path, filename: str) -> dict:
    path = root / "experiments/evidence" / filename
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise ValueError("Keyboard interruption must be a bounded regular publication")
    source = json.loads(path.read_bytes())
    rejected = filename == "astra_native_keyboard_rejection_20260907.json"
    schema = ("fortgym.native-keyboard-input-rejection-summary/v1" if rejected
              else "fortgym.native-keyboard-interruption/v1")
    reason = "unsupported_model_key_names_stopped_harness" if rejected else "native_tick_timeout"
    if (
        source["schema_version"] != schema
        or source["model"] != "gpt-6-astra"
        or source["reasoning_effort"] != "medium"
        or source["control_profile"] != "native_keyboard/v2"
        or source["observation_profile"] != "native_screen_text/v1"
        or source["captured_screen_size"] != [120, 40]
        or re.fullmatch("[a-f0-9]{40}", source["source_revision"]) is None
        or source["terminal_reason"] != reason
        or source["independent_retained_evidence_audit_passed"] is not True
        or source["teardown_verified"] is not True
        or source["recovery_requires_reconciliation"] is not True
        or source["forensic_save_is_resumable_checkpoint"] is not False
        or (rejected and source.get("historical_run_reclassified_as_success") is not False)
    ):
        raise ValueError("Published keyboard interruption has inconsistent provenance")
    progress = {key: source["progress"][key] for key in (
        "committed_decisions", "returned_model_decisions", "native_key_events_confirmed",
        "failed_tail_key_events_confirmed", "elapsed_native_ticks",
        "latest_verified_checkpoint_cursor", "uncheckpointed_committed_decisions",
    )}
    usage = {key: source["usage"][key] for key in (
        "campaign_tokens", "all_attempt_tokens", "historical_failed_delivery_tokens",
    )}
    usage["failed_tail_model_tokens_included"] = source["usage"][
        "rejected_response_tokens_included" if rejected else "failed_tail_model_tokens_included"
    ]
    if any(type(value) is not int or value < 0 for value in (*progress.values(), *usage.values())):
        raise ValueError("Invalid interruption progress or usage counter")
    if (
        progress["returned_model_decisions"] != progress["committed_decisions"] + 1
        or (rejected and progress["failed_tail_key_events_confirmed"] != 0)
        or not 0 < progress["latest_verified_checkpoint_cursor"] <= progress["committed_decisions"]
        or progress["uncheckpointed_committed_decisions"]
        != progress["committed_decisions"] - progress["latest_verified_checkpoint_cursor"]
        or usage["all_attempt_tokens"]
        != usage["campaign_tokens"] + usage["historical_failed_delivery_tokens"]
        or not 0 < usage["failed_tail_model_tokens_included"] <= usage["campaign_tokens"]
        or source["usage"]["reported_charge_usd"] is not None
        or source["usage"]["cost_basis"] != "codex_subscription_charge_unreported/v1"
    ):
        raise ValueError("Interruption usage and checkpoint boundary do not reconcile")
    return {
        "interruption_id": filename.removesuffix(".json"),
        "source_revision": source["source_revision"],
        "terminal_reason": reason,
        "progress": progress,
        "usage": {**usage, "reported_charge_usd": None,
                  "cost_basis": "codex_subscription_charge_unreported/v1"},
        "teardown_verified": True,
        "recovery_requires_reconciliation": True,
        "fortress_success": "not_assessed_in_public_operational_summary",
        "evidence_path": "experiments/evidence/" + filename,
    }


def _recovery(root: Path, filename: str, interruptions: list[dict]) -> dict:
    path = root / "experiments/evidence" / filename
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise ValueError("Keyboard recovery must be a bounded regular publication")
    source = json.loads(path.read_bytes())
    original = next((row for row in interruptions
                     if row["interruption_id"] == source["original_interruption"]), None)
    if (
        original is None
        or source["schema_version"] != "fortgym.native-keyboard-recovery-summary/v1"
        or source["model"] != "gpt-6-astra"
        or source["reasoning_effort"] != "medium"
        or source["control_profile"] != "native_keyboard/v2"
        or source["observation_profile"] != "native_screen_text/v1"
        or re.fullmatch("[a-f0-9]{40}", source["source_revision"]) is None
        or re.fullmatch("[a-f0-9]{64}", source["checkpoint_sha256"]) is None
        or source["original_failed_run_reclassified_as_success"] is not False
        or any(source[key] is not True for key in (
            "independent_retained_evidence_audit_passed", "native_recovery_checkpoint_verified",
            "model_memory_and_usage_unchanged", "source_bytes_unchanged",
            "original_failure_preserved", "teardown_verified",
        ))
    ):
        raise ValueError("Published recovery has inconsistent provenance")
    counters = {key: source[key] for key in (
        "parent_checkpoint_cursor", "next_step", "elapsed_native_ticks",
        "returned_model_decisions", "model_calls_to_recover", "native_keys_to_recover",
        "native_ticks_to_recover", "campaign_tokens",
        "all_attempt_tokens_including_historical_failures",
    )}
    if any(type(value) is not int or value < 0 for value in counters.values()):
        raise ValueError("Invalid recovery counter")
    progress, usage = original["progress"], original["usage"]
    if (
        counters["next_step"] != counters["returned_model_decisions"]
        or counters["next_step"] != progress["returned_model_decisions"]
        or counters["parent_checkpoint_cursor"] != progress["latest_verified_checkpoint_cursor"]
        or counters["elapsed_native_ticks"] != progress["elapsed_native_ticks"]
        or any(counters[key] != 0 for key in (
            "model_calls_to_recover", "native_keys_to_recover", "native_ticks_to_recover",
        ))
        or counters["campaign_tokens"] != usage["campaign_tokens"]
        or counters["all_attempt_tokens_including_historical_failures"] != usage["all_attempt_tokens"]
        or source["reported_campaign_charge_usd"] is not None
        or source["cost_basis"] != "codex_subscription_charge_unreported/v1"
    ):
        raise ValueError("Recovery changes the retained interruption state or usage")
    return {
        "recovery_id": filename.removesuffix(".json"),
        "original_interruption": original["interruption_id"],
        "source_revision": source["source_revision"],
        "checkpoint_sha256": source["checkpoint_sha256"],
        "checkpoint_cursor": counters["next_step"],
        "parent_checkpoint_cursor": counters["parent_checkpoint_cursor"],
        "returned_model_decisions": counters["returned_model_decisions"],
        "elapsed_native_ticks": counters["elapsed_native_ticks"],
        "model_calls_to_recover": 0,
        "native_keys_to_recover": 0,
        "native_ticks_to_recover": 0,
        "original_failure_preserved": True,
        "teardown_verified": True,
        "usage": {key: usage[key] for key in (
            "campaign_tokens", "all_attempt_tokens", "reported_charge_usd", "cost_basis",
        )},
        "evidence_path": "experiments/evidence/" + filename,
    }


def keyboard_campaign_records(root: Path = PROJECT_ROOT) -> dict:
    records = []
    for filename in PUBLISHED:
        path = root / "experiments/evidence" / filename
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
            raise ValueError("Keyboard evidence must be a bounded regular publication")
        source = json.loads(path.read_bytes())
        if (
            source["schema_version"] != "fortgym.native-interface-acceptance-summary/v1"
            or source["model"] != "gpt-6-astra"
            or source["reasoning_effort"] != "medium"
            or source["control_profile"] != "native_keyboard/v2"
            or source["observation_profile"] != "native_screen_text/v1"
            or source["captured_screen_size"] != [120, 40]
            or re.fullmatch("[a-f0-9]{40}", source["source_revision"]) is None
            or source["usage"]["reported_charge_usd"] is not None
            or source["campaign_result"]["independent_retained_evidence_audit_passed"] is not True
            or not source["attempts"]
            or any(attempt["teardown_verified"] is not True for attempt in source["attempts"])
        ):
            raise ValueError("Published keyboard milestone has inconsistent provenance")
        progress = {key: source["campaign_result"][key] for key in PROGRESS_FIELDS}
        for key in PROGRESS_FIELDS[:-1]:
            if type(progress[key]) is not int or progress[key] < 0:
                raise ValueError("Invalid keyboard progress counter")
        cursors = progress["checkpoint_cursors"]
        if (
            not isinstance(cursors, list)
            or not cursors
            or any(type(cursor) is not int or cursor < 1 for cursor in cursors)
            or cursors != sorted(set(cursors))
            or cursors[-1] != progress["model_decisions"]
        ):
            raise ValueError("Published keyboard checkpoint does not cover its decisions")
        usage = source["usage"]
        for key in (
            "codex_invocations_across_all_attempts",
            "total_tokens",
            "failed_delivery_tokens",
        ):
            if type(usage[key]) is not int or usage[key] < 0:
                raise ValueError("Invalid published subscription usage")
        if usage["total_tokens"] != progress["cumulative_tokens"] + usage["failed_delivery_tokens"]:
            raise ValueError("Campaign and failed-delivery usage do not reconcile")
        if usage["codex_invocations_across_all_attempts"] < progress["model_decisions"]:
            raise ValueError("Published invocation count is below committed decisions")
        records.append(
            {
                "milestone_id": filename.removesuffix(".json"),
                "model": source["model"],
                "reasoning_effort": source["reasoning_effort"],
                "control_profile": source["control_profile"],
                "observation_profile": source["observation_profile"],
                "screen_size": source["captured_screen_size"],
                "progress": progress,
                "usage": {
                    "campaign_tokens": progress["cumulative_tokens"],
                    "all_attempt_tokens": usage["total_tokens"],
                    "failed_delivery_tokens": usage["failed_delivery_tokens"],
                    "codex_invocations": usage["codex_invocations_across_all_attempts"],
                    "reported_charge_usd": None,
                    "cost_basis": "codex_subscription_charge_unreported/v1",
                },
                "teardown_verified": True,
                "fortress_success": "not_assessed_in_public_operational_summary",
                "source_revision": source["source_revision"],
                "evidence_path": "experiments/evidence/" + filename,
            }
        )
    interruptions = [_interruption(root, filename) for filename in INTERRUPTIONS]
    return {
        "schema_version": "fortgym.public-keyboard-milestones/v1",
        "live_tracking": False,
        "milestones": records,
        "interruptions": interruptions,
        "recoveries": [_recovery(root, filename, interruptions) for filename in RECOVERIES],
    }
