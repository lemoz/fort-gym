"""Recorded prelaunch pauses, separate from gameplay and live account status."""

from pathlib import Path
import re

from .campaign_keyboard_presave import _hash, _matches, _read
from .campaign_keyboard_records import PROJECT_ROOT, keyboard_campaign_records

PUBLISHED = "astra_native_keyboard_prelaunch_pause_20260910z.json"
SCHEMA = "fortgym.public-keyboard-admission/v1"


def admission_record(root: Path = PROJECT_ROOT) -> dict:
    source = _read(root, PUBLISHED)
    records = keyboard_campaign_records(root)
    candidates = [row for row in records["completed_windows"]
                  if row["window_id"] == source.get("parent_record")]
    if len(candidates) != 1:
        raise ValueError("Admission pause needs one verified saved parent")
    parent = candidates[0]
    expected = {
        "schema_version": "fortgym.keyboard-prelaunch-pause/v1",
        "model": parent["model"], "reasoning_effort": parent["reasoning_effort"],
        "status": "budget_limited_pause", "reason": "included_usage_headroom_threshold",
        "phase": "before_vm_start", "checkpoint_sha256": parent["checkpoint_sha256"],
        "checkpoint_cursor": parent["progress"]["checkpoint_cursor"],
        "saved_elapsed_ticks": parent["progress"]["saved_elapsed_ticks"],
        "campaign_responses": parent["progress"]["cumulative_model_responses"],
        "campaign_tokens": parent["usage"]["campaign_tokens"],
        "all_attempt_tokens": parent["usage"]["all_attempt_tokens"],
        "new_model_calls": 0, "new_tokens": 0, "new_game_ticks": 0,
        "cloud_vms_created": 0, "vm_started": False, "game_started": False,
        "api_fallback_used": False, "usage_reset_used": False,
        "checkpoint_unchanged": True, "fresh_checkpoint_load_verified": False,
        "independent_audit_passed": True, "reported_charge_usd": None,
    }
    _matches(source, expected)
    if not isinstance(source.get("run_id"), str) or not re.fullmatch(r"[a-z0-9-]{1,100}", source["run_id"]):
        raise ValueError("Invalid admission run identity")
    _hash(source.get("source_revision"), 40)
    for key in ("independent_audit_sha256", "condition_sha256", "window_sha256"):
        _hash(source.get(key), 64)
    # Only experiment-local evidence is public. Raw account quota, reset times,
    # paths, prompts and private operator receipts never pass through this API.
    return {
        **{key: source[key] for key in expected},
        "schema_version": SCHEMA, "recorded_only": True,
        "run_id": source["run_id"], "source_revision": source["source_revision"],
        "parent_record": parent["window_id"],
        "evidence_path": "experiments/evidence/" + PUBLISHED,
    }
