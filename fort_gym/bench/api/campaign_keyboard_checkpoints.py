"""Allowlisted, non-content projection of lost native checkpoint tails."""

import json
import re
from pathlib import Path

CHECKPOINT_FAILURES = ("astra_native_keyboard_checkpoint_failure_20260907.json",)
CHECKPOINT_RECOVERIES = (
    "astra_native_keyboard_settled_recovery_20260908.json",
    "astra_native_keyboard_runtime_recovery_20260908.json",
)


def checkpoint_failure(root: Path, filename: str, recoveries: list[dict]) -> dict:
    path = root / "experiments/evidence" / filename
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise ValueError("Checkpoint failure must be a bounded regular publication")
    source = json.loads(path.read_bytes())
    identities = {
        "schema_version": "fortgym.native-keyboard-checkpoint-failure-summary/v1",
        "model": "gpt-6-astra",
        "reasoning_effort": "medium",
        "control_profile": "native_keyboard/v2",
        "observation_profile": "native_screen_text/v1",
        "terminal_reason": "native_save_completion_timeout",
    }
    if (
        any(source.get(key) != value for key, value in identities.items())
        or re.fullmatch("[a-f0-9]{40}", source["source_revision"]) is None
        or source["checkpoint_verified"] is not False
        or any(
            source[key] is not True
            for key in (
                "independent_retained_evidence_audit_passed",
                "teardown_verified",
                "original_failed_window_preserved",
                "original_trace_and_usage_prefix_unchanged",
            )
        )
    ):
        raise ValueError("Checkpoint failure provenance is inconsistent")
    progress = {
        key: source["progress"][key]
        for key in (
            "starting_checkpoint_cursor",
            "retained_trace_cursor",
            "returned_model_responses",
            "new_accepted_model_responses",
            "committed_elapsed_ticks_in_trace",
            "last_resumable_checkpoint_cursor",
            "last_saved_elapsed_ticks",
            "unsaved_new_native_ticks",
        )
    }
    usage = {
        key: source["usage"][key]
        for key in (
            "new_tokens",
            "campaign_tokens",
            "all_attempt_tokens",
            "historical_failed_delivery_tokens",
        )
    }
    if any(type(value) is not int or value < 0 for value in (*progress.values(), *usage.values())):
        raise ValueError("Checkpoint failure counters are invalid")
    previous = next(
        (
            row
            for row in recoveries
            if row["checkpoint_cursor"] == progress["starting_checkpoint_cursor"]
        ),
        None,
    )
    if (
        previous is None
        or progress["last_resumable_checkpoint_cursor"] != previous["checkpoint_cursor"]
        or progress["last_saved_elapsed_ticks"] != previous["elapsed_native_ticks"]
        or progress["retained_trace_cursor"] != progress["returned_model_responses"]
        or progress["new_accepted_model_responses"] <= 0
        or progress["retained_trace_cursor"] - progress["starting_checkpoint_cursor"]
        != progress["new_accepted_model_responses"]
        or progress["committed_elapsed_ticks_in_trace"] - progress["last_saved_elapsed_ticks"]
        != progress["unsaved_new_native_ticks"]
        or source["progress"]["new_native_save_matches_prior_checkpoint"] is not True
        or source["progress"]["newer_native_state_resumable"] is not False
        or usage["new_tokens"] <= 0
        or usage["campaign_tokens"] != previous["usage"]["campaign_tokens"] + usage["new_tokens"]
        or usage["all_attempt_tokens"]
        != previous["usage"]["all_attempt_tokens"] + usage["new_tokens"]
        or usage["all_attempt_tokens"]
        != usage["campaign_tokens"] + usage["historical_failed_delivery_tokens"]
        or source["usage"]["reported_charge_usd"] is not None
        or source["usage"]["cost_basis"] != "codex_subscription_charge_unreported/v1"
    ):
        raise ValueError("Checkpoint failure must retain the unsaved tail and all usage")
    return {
        "failure_id": filename.removesuffix(".json"),
        "source_revision": source["source_revision"],
        "terminal_reason": source["terminal_reason"],
        "progress": progress,
        "usage": {
            **usage,
            "reported_charge_usd": None,
            "cost_basis": "codex_subscription_charge_unreported/v1",
        },
        "newer_native_state_resumable": False,
        "teardown_verified": True,
        "evidence_path": "experiments/evidence/" + filename,
    }


def settled_checkpoint_recovery(root: Path, filename: str, reviews: list[dict]) -> dict:
    """Publish verified forward recovery without changing the historical failure."""
    path = root / "experiments/evidence" / filename
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise ValueError("Checkpoint recovery must be a bounded regular publication")
    source = json.loads(path.read_bytes())
    original = next((row for row in reviews if row["review_id"] == source["original_review"]), None)
    runtime_source = source.get("schema_version") == "fortgym.native-keyboard-settled-recovery-summary/v2"
    identities = {
        "schema_version": "fortgym.native-keyboard-settled-recovery-summary/" + ("v2" if runtime_source else "v1"),
        "model": "gpt-6-astra",
        "reasoning_effort": "medium",
        "control_profile": "native_keyboard/v2",
        "observation_profile": "native_screen_text/v1",
        "snapshot_profile": "native_menu_preserving_save/v3" if runtime_source else "native_menu_preserving_save/v2",
        **({"recovery_source_kind": "retained_runtime_save/v1"} if runtime_source else {}),
    }
    if (
        original is None
        or original["terminal_reason"] != (
            "native_menu_identity_changed_during_save" if runtime_source else "native_screen_changed_during_save"
        )
        or any(source.get(key) != value for key, value in identities.items())
        or re.fullmatch("[a-f0-9]{40}", source["source_revision"]) is None
        or re.fullmatch("[a-f0-9]{64}", source["checkpoint_sha256"]) is None
        or source["parent_checkpoint_sha256"] != original["parent_checkpoint_sha256"]
        or source["checkpoint_sha256"] == source["parent_checkpoint_sha256"]
        or type(source["screen_unchanged"]) is not bool
        or any(source[key] is not True for key in (
            "independent_retained_evidence_audit_passed", "native_checkpoint_verified",
            "fresh_native_reload_verified", "source_and_trace_bytes_unchanged",
            "model_memory_and_usage_unchanged", "inherited_discontinuity_unchanged",
            "semantic_snapshot_verified", "original_failure_preserved", "teardown_verified",
        ))
        or any(source[key] is not False for key in (
            "new_discontinuity_created", "historical_failed_run_reclassified_as_success",
        ))
    ):
        raise ValueError("Settled checkpoint recovery provenance is inconsistent")
    counters = {key: source[key] for key in (
        "parent_checkpoint_cursor", "checkpoint_cursor", "elapsed_native_ticks",
        "cumulative_model_responses", "model_calls_to_recover", "native_keys_to_recover",
        "native_ticks_to_recover", "campaign_tokens", "all_attempt_tokens",
    )}
    if any(type(value) is not int or value < 0 for value in counters.values()):
        raise ValueError("Settled checkpoint recovery counters are invalid")
    progress, usage = original["progress"], original["usage"]
    if (
        counters["parent_checkpoint_cursor"] != progress["latest_verified_checkpoint_cursor"]
        or counters["checkpoint_cursor"] != progress["trace_cursor"]
        or counters["elapsed_native_ticks"] != progress["trace_elapsed_ticks"]
        or counters["cumulative_model_responses"] != progress["cumulative_model_responses"]
        or any(counters[key] != 0 for key in (
            "model_calls_to_recover", "native_keys_to_recover", "native_ticks_to_recover",
        ))
        or counters["campaign_tokens"] != usage["campaign_tokens"]
        or counters["all_attempt_tokens"] != usage["all_attempt_tokens"]
        or source["reported_charge_usd"] is not None
        or source["cost_basis"] != "codex_subscription_charge_unreported/v1"
    ):
        raise ValueError("Settled recovery must preserve all progress, memory and usage")
    return {
        "recovery_id": filename.removesuffix(".json"),
        "recovery_kind": "settled_checkpoint",
        "original_review": original["review_id"],
        "source_revision": source["source_revision"],
        "checkpoint_sha256": source["checkpoint_sha256"],
        "snapshot_profile": source["snapshot_profile"],
        "parent_checkpoint_cursor": counters["parent_checkpoint_cursor"],
        "checkpoint_cursor": counters["checkpoint_cursor"],
        "returned_model_decisions": counters["cumulative_model_responses"],
        "elapsed_native_ticks": counters["elapsed_native_ticks"],
        "model_calls_to_recover": 0,
        "native_keys_to_recover": 0,
        "native_ticks_to_recover": 0,
        "fresh_native_reload_verified": True,
        "original_failure_preserved": True,
        "new_discontinuity_created": False,
        "teardown_verified": True,
        "usage": {key: usage[key] for key in (
            "campaign_tokens", "all_attempt_tokens", "reported_charge_usd", "cost_basis",
        )},
        "evidence_path": "experiments/evidence/" + filename,
    }
