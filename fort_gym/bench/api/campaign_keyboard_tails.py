"""Explicit public records for a continuation timeout and its forward recovery."""

from __future__ import annotations

import json
import re
from pathlib import Path

TAIL_INTERRUPTION = "astra_native_keyboard_workshop_timeout_20260908.json"
TAIL_RECOVERIES = ("astra_native_keyboard_workshop_recovery_20260908.json",)
COUNTERS = (
    "parent_checkpoint_cursor",
    "trace_cursor",
    "new_returned_model_decisions",
    "new_committed_decisions",
    "cumulative_model_responses",
    "failed_tail_keys_confirmed",
    "failed_tail_ticks_advanced",
    "new_elapsed_ticks",
    "trace_elapsed_ticks",
    "latest_verified_checkpoint_cursor",
    "latest_verified_checkpoint_elapsed_ticks",
    "new_tokens",
    "campaign_tokens",
    "all_attempt_tokens",
)


def _read(root: Path, filename: str, schema: str) -> dict:
    path = root / "experiments/evidence" / filename
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise ValueError("Tail evidence must be a bounded regular publication")
    source = json.loads(path.read_bytes())
    if (
        source.get("schema_version") != schema
        or source.get("model") != "gpt-6-astra"
        or source.get("reasoning_effort") != "medium"
        or source.get("control_profile") != "native_keyboard/v2"
        or source.get("observation_profile") != "native_screen_text/v1"
        or source.get("captured_screen_size") != [120, 40]
        or source.get("snapshot_profile") != "native_menu_preserving_save/v3"
        or re.fullmatch("[a-f0-9]{40}", source.get("source_revision", "")) is None
        or "reported_charge_usd" not in source
        or source["reported_charge_usd"] is not None
        or source.get("cost_basis") != "codex_subscription_charge_unreported/v1"
        or source.get("independent_retained_evidence_audit_passed") is not True
        or source.get("teardown_verified") is not True
    ):
        raise ValueError("Tail evidence has inconsistent provenance")
    return source


def continuation_interruption(root: Path, filename: str, parents: list[dict]) -> dict:
    source = _read(root, filename, "fortgym.native-keyboard-continuation-interruption/v1")
    parent = next(
        (row for row in parents if row["continuation_id"] == source["parent_record"]), None
    )
    if parent is None:
        raise ValueError("Tail interruption lacks a published parent")
    values = {key: source[key] for key in COUNTERS}
    if any(type(value) is not int or value < 0 for value in values.values()):
        raise ValueError("Invalid tail counter")
    progress, usage = parent["progress"], parent["usage"]
    if (
        source["parent_checkpoint_sha256"] != parent["checkpoint_sha256"]
        or source["parent_checkpoint_cursor"] != parent["checkpoint_cursor"]
        or source["latest_verified_checkpoint_cursor"] != parent["checkpoint_cursor"]
        or source["trace_cursor"] != parent["checkpoint_cursor"] + source["new_committed_decisions"]
        or source["new_returned_model_decisions"] != source["new_committed_decisions"] + 1
        or source["cumulative_model_responses"]
        != progress["cumulative_model_responses"] + source["new_returned_model_decisions"]
        or source["trace_elapsed_ticks"]
        != progress["retained_elapsed_ticks"] + source["new_elapsed_ticks"]
        or source["latest_verified_checkpoint_elapsed_ticks"] != progress["retained_elapsed_ticks"]
        or source["campaign_tokens"] != usage["campaign_tokens"] + source["new_tokens"]
        or source["all_attempt_tokens"] != usage["all_attempt_tokens"] + source["new_tokens"]
        or source["failed_tail_ticks_advanced"] != 0
        or source["failed_tail_keys_confirmed"] < 1
        or source["terminal_reason"] != "workshop_add_job_menu_tick_timeout"
        or any(
            source[key] is not True
            for key in (
                "original_prefixes_unchanged",
                "inherited_discontinuity_unchanged",
                "forensic_save_retained",
                "recovery_requires_reconciliation",
            )
        )
        or source["forensic_save_is_resumable_checkpoint"] is not False
        or source["historical_failed_run_reclassified_as_success"] is not False
    ):
        raise ValueError("Tail interruption must preserve parent progress and usage")
    return {
        "interruption_id": filename.removesuffix(".json"),
        "parent_record": source["parent_record"],
        "parent_checkpoint_sha256": source["parent_checkpoint_sha256"],
        "source_revision": source["source_revision"],
        "terminal_reason": source["terminal_reason"],
        "progress": {key: value for key, value in values.items() if "token" not in key},
        "usage": {
            key: source[key]
            for key in (
                "new_tokens",
                "campaign_tokens",
                "all_attempt_tokens",
                "reported_charge_usd",
                "cost_basis",
            )
        },
        "teardown_verified": True,
        "recovery_requires_reconciliation": True,
        "evidence_path": "experiments/evidence/" + filename,
    }


def continuation_recovery(root: Path, filename: str, interruptions: list[dict]) -> dict:
    source = _read(root, filename, "fortgym.native-keyboard-continuation-recovery/v1")
    parent = next(
        (row for row in interruptions if row["interruption_id"] == source["original_interruption"]),
        None,
    )
    if parent is None:
        raise ValueError("Tail recovery lacks its original interruption")
    counters = {
        key: source[key]
        for key in (
            "parent_checkpoint_cursor",
            "checkpoint_cursor",
            "returned_model_decisions",
            "elapsed_native_ticks",
            "model_calls_to_recover",
            "native_keys_to_recover",
            "native_ticks_to_recover",
            "campaign_tokens",
            "all_attempt_tokens",
        )
    }
    if any(type(value) is not int or value < 0 for value in counters.values()):
        raise ValueError("Invalid tail recovery counter")
    progress, usage = parent["progress"], parent["usage"]
    if (
        source["parent_checkpoint_sha256"] != parent["parent_checkpoint_sha256"]
        or re.fullmatch("[a-f0-9]{64}", source["checkpoint_sha256"]) is None
        or source["checkpoint_sha256"] == source["parent_checkpoint_sha256"]
        or source["parent_checkpoint_cursor"] != progress["parent_checkpoint_cursor"]
        or source["checkpoint_cursor"] != progress["trace_cursor"] + 1
        or source["returned_model_decisions"] != progress["cumulative_model_responses"]
        or source["elapsed_native_ticks"] != progress["trace_elapsed_ticks"]
        or any(
            source[key] != 0
            for key in (
                "model_calls_to_recover",
                "native_keys_to_recover",
                "native_ticks_to_recover",
            )
        )
        or any(source[key] != usage[key] for key in ("campaign_tokens", "all_attempt_tokens"))
        or any(
            source[key] is not True
            for key in (
                "source_bytes_unchanged",
                "model_memory_and_usage_unchanged",
                "original_failure_preserved",
                "inherited_discontinuity_unchanged",
                "native_recovery_checkpoint_verified",
                "fresh_native_checkpoint_reload_verified",
            )
        )
        or source["new_discontinuity_created"] is not False
        or source["original_failed_run_reclassified_as_success"] is not False
    ):
        raise ValueError(
            "Tail recovery must preserve all original progress, responses and failures"
        )
    return {
        "recovery_id": filename.removesuffix(".json"),
        "recovery_kind": "clock_tail",
        "original_interruption": parent["interruption_id"],
        "source_revision": source["source_revision"],
        "checkpoint_sha256": source["checkpoint_sha256"],
        **{key: value for key, value in counters.items() if "token" not in key},
        "usage": {
            key: usage[key]
            for key in (
                "campaign_tokens",
                "all_attempt_tokens",
                "reported_charge_usd",
                "cost_basis",
            )
        },
        "snapshot_profile": source["snapshot_profile"],
        "original_failure_preserved": True,
        "teardown_verified": True,
        "fresh_native_checkpoint_reload_verified": True,
        "evidence_path": "experiments/evidence/" + filename,
    }
