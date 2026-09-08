"""Project authored restart evidence without exposing private gameplay content."""

import json
import re
from pathlib import Path

RESTARTS = ("astra_native_keyboard_restart_20260908.json",)


def keyboard_restart(root: Path, filename: str, failures: list[dict], recoveries: list[dict]) -> dict:
    path = root / "experiments/evidence" / filename
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise ValueError("Restart evidence must be a bounded regular publication")
    source = json.loads(path.read_bytes())
    identities = {
        "schema_version": "fortgym.native-keyboard-restart-summary/v1",
        "model": "gpt-6-astra",
        "reasoning_effort": "medium",
        "control_profile": "native_keyboard/v2",
        "observation_profile": "native_screen_text/v1",
        "snapshot_profile": "native_menu_preserving_save/v1",
    }
    if (
        any(source.get(key) != value for key, value in identities.items())
        or re.fullmatch("[a-f0-9]{40}", source["source_revision"]) is None
        or any(re.fullmatch("[a-f0-9]{64}", source[key]) is None for key in (
            "parent_checkpoint_sha256", "checkpoint_sha256",
        ))
        or any(source[key] is not True for key in (
            "independent_retained_evidence_audit_passed", "native_checkpoint_verified",
            "teardown_verified", "source_checkpoint_and_failed_window_unchanged",
            "model_memory_restored_from_checkpoint",
        ))
        or any(source[key] is not False for key in (
            "uninterrupted_campaign", "historical_tail_replayed", "independent_comparison_attempt",
        ))
    ):
        raise ValueError("Restart provenance is inconsistent")
    progress = {key: source["progress"][key] for key in (
        "restored_checkpoint_cursor", "checkpoint_cursor", "new_model_responses",
        "new_accepted_decisions", "cumulative_model_responses", "new_elapsed_ticks",
        "retained_elapsed_ticks", "discarded_native_ticks",
    )}
    usage = {key: source["usage"][key] for key in (
        "new_tokens", "campaign_tokens", "all_attempt_tokens", "lost_tail_tokens_retained",
        "historical_failed_delivery_tokens",
    )}
    if any(type(value) is not int or value < 0 for value in (*progress.values(), *usage.values())):
        raise ValueError("Restart counters are invalid")
    failure = next((row for row in failures
                    if row["failure_id"] == source["original_failure"]), None)
    parent = next((row for row in recoveries
                   if row["checkpoint_sha256"] == source["parent_checkpoint_sha256"]), None)
    if failure is None or parent is None:
        raise ValueError("Restart must reference the retained failure and verified parent")
    old_progress, old_usage = failure["progress"], failure["usage"]
    if (
        progress["restored_checkpoint_cursor"] != parent["checkpoint_cursor"]
        or progress["restored_checkpoint_cursor"] != old_progress["last_resumable_checkpoint_cursor"]
        or source["checkpoint_sha256"] == source["parent_checkpoint_sha256"]
        or progress["new_model_responses"] <= 0
        or progress["new_accepted_decisions"] > progress["new_model_responses"]
        or progress["checkpoint_cursor"]
        != progress["restored_checkpoint_cursor"] + progress["new_model_responses"]
        or progress["cumulative_model_responses"]
        != old_progress["returned_model_responses"] + progress["new_model_responses"]
        or progress["retained_elapsed_ticks"]
        != parent["elapsed_native_ticks"] + progress["new_elapsed_ticks"]
        or progress["discarded_native_ticks"] != old_progress["unsaved_new_native_ticks"]
        or usage["new_tokens"] <= 0
        or usage["campaign_tokens"] != old_usage["campaign_tokens"] + usage["new_tokens"]
        or usage["all_attempt_tokens"] != old_usage["all_attempt_tokens"] + usage["new_tokens"]
        or usage["lost_tail_tokens_retained"] != old_usage["new_tokens"]
        or usage["historical_failed_delivery_tokens"] != old_usage["historical_failed_delivery_tokens"]
        or source["usage"]["reported_charge_usd"] is not None
        or source["usage"]["cost_basis"] != "codex_subscription_charge_unreported/v1"
    ):
        raise ValueError("Restart must retain all usage and distinguish the lost native branch")
    return {
        "restart_id": filename.removesuffix(".json"),
        "original_failure": failure["failure_id"],
        "source_revision": source["source_revision"],
        "parent_checkpoint_sha256": source["parent_checkpoint_sha256"],
        "checkpoint_sha256": source["checkpoint_sha256"],
        "progress": progress,
        "usage": {**usage, "reported_charge_usd": None,
                  "cost_basis": "codex_subscription_charge_unreported/v1"},
        "uninterrupted_campaign": False,
        "historical_tail_replayed": False,
        "independent_comparison_attempt": False,
        "native_checkpoint_verified": True,
        "teardown_verified": True,
        "fortress_success": "not_assessed_in_public_operational_summary",
        "evidence_path": "experiments/evidence/" + filename,
    }
