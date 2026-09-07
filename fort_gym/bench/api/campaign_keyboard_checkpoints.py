"""Allowlisted, non-content projection of lost native checkpoint tails."""

import json
import re
from pathlib import Path

CHECKPOINT_FAILURES = ("astra_native_keyboard_checkpoint_failure_20260907.json",)


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
