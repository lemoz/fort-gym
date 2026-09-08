"""Public pre-save failures and runner diagnostics, never completed play."""

from __future__ import annotations

import json
import re
from pathlib import Path

PRESAVE_FAILURES = ("astra_native_keyboard_presave_failure_20260908.json",)
SAVE_ACCEPTANCES = ("native_status_stack_acceptance_20260908.json",)
PROGRESS = (
    "observed_trace_next_step", "observed_trace_elapsed_ticks", "checkpointed_elapsed_ticks",
    "unsaved_new_native_ticks", "new_model_calls", "new_accepted_decisions",
    "new_rejected_decisions", "accounted_model_responses", "advancing_decisions",
    "zero_tick_decisions",
)
USAGE = ("new_tokens", "campaign_tokens", "all_attempt_tokens")
OUTCOME_KEYS = (
    "population", "completed_farms", "completed_beds", "completed_workshops",
    "recorded_dead_citizens", "food_stock", "drink_stock",
)


def _read(root: Path, filename: str) -> dict:
    path = root / "experiments/evidence" / filename
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise ValueError("Save publication must be a bounded regular file")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("Save publication must be an object")
    return value


def _matches(value: dict, expected: dict) -> None:
    if not isinstance(value, dict) or any(
        type(value.get(key)) is not type(item) or value[key] != item
        for key, item in expected.items()
    ):
        raise ValueError("Save publication provenance is inconsistent")


def _numbers(value: dict, keys: tuple[str, ...]) -> dict:
    if not isinstance(value, dict) or any(
        type(value.get(key)) is not int or value[key] < 0 for key in keys
    ):
        raise ValueError("Save publication counters are invalid")
    return {key: value[key] for key in keys}


def _hash(value: object, length: int) -> None:
    if not isinstance(value, str) or re.fullmatch(f"[a-f0-9]{{{length}}}", value) is None:
        raise ValueError("Save publication digest is invalid")


def presave_failure(root: Path, filename: str, parents: list[dict]) -> dict:
    source = _read(root, filename)
    parent = next((row for row in parents if row["continuation_id"] == source["parent_record"]), None)
    if parent is None:
        raise ValueError("Pre-save failure has no published parent")
    _matches(source, {
        "schema_version": "fortgym.native-keyboard-presave-failure-summary/v1",
        "status": "failed", "model": "gpt-6-astra", "reasoning_effort": "medium",
        "control_profile": "native_keyboard/v2", "observation_profile": "native_screen_text/v1",
        "snapshot_profile": "native_menu_preserving_save/v3", "captured_screen_size": [120, 40],
        "independent_failure_audit_passed": True, "teardown_verified": True,
        "original_checkpoint_unchanged": True, "original_failure_preserved": True,
        "last_checkpoint_save_files_unchanged_except_event_log": True,
        "new_checkpoint_created": False, "new_restart_performed": False,
        "last_verified_checkpoint_cursor": parent["checkpoint_cursor"],
        "last_verified_checkpoint_sha256": parent["checkpoint_sha256"],
        "inherited_save_loss_restarts": parent["progress"]["native_save_loss_restarts"],
        "inherited_discarded_native_ticks": parent["progress"]["discarded_native_ticks"],
    })
    _matches(source["failure"], {
        "stage": "identity_probe_before_native_save_request", "native_save_requested": False,
        "native_window_status": "failed", "rejected_stack_entry_type": "not_recorded",
        "underlying_stack_cause": "unverified",
    })
    _hash(source["source_revision"], 40)
    _hash(source["private_failure_audit_sha256"], 64)
    progress, usage = _numbers(source["progress"], PROGRESS), _numbers(source["usage"], USAGE)
    _matches(source["usage"], {
        "reported_charge_usd": None, "cost_basis": "codex_subscription_charge_unreported/v1",
    })
    if (
        not 0 < progress["new_model_calls"]
        or progress["new_accepted_decisions"] + progress["new_rejected_decisions"] != progress["new_model_calls"]
        or progress["advancing_decisions"] + progress["zero_tick_decisions"] != progress["new_model_calls"]
        or progress["observed_trace_next_step"] != parent["checkpoint_cursor"] + progress["new_model_calls"]
        or progress["checkpointed_elapsed_ticks"] != parent["progress"]["retained_elapsed_ticks"]
        or progress["observed_trace_elapsed_ticks"] != progress["checkpointed_elapsed_ticks"] + progress["unsaved_new_native_ticks"]
        or progress["accounted_model_responses"] != parent["progress"]["cumulative_model_responses"] + progress["new_model_calls"]
        or any(usage[key] != parent["usage"][key] + usage["new_tokens"]
               for key in ("campaign_tokens", "all_attempt_tokens"))
    ):
        raise ValueError("Pre-save failure progress does not reconcile with its checkpoint")
    outcomes = source["observed_unsaved_outcomes"]
    _matches(outcomes, {
        "food_final_observation_is_saved": False, "sustainability": "not_established",
        "production_and_consumption": "not_measured", "accessibility": "not_assessed",
    })
    counts = {key: _numbers(outcomes["counts"][key], ("start", "end")) for key in OUTCOME_KEYS}
    coverage = _numbers(outcomes, (
        "food_observed_boundaries", "food_complete_measurements", "food_unknown_measurements",
    ))
    if coverage["food_observed_boundaries"] != progress["new_model_calls"] + 1 or (
        coverage["food_complete_measurements"] + coverage["food_unknown_measurements"]
        != coverage["food_observed_boundaries"]
    ):
        raise ValueError("Pre-save failure food coverage does not reconcile")
    return {
        "failure_id": filename.removesuffix(".json"), "status": "failed",
        "parent_record": source["parent_record"], "source_revision": source["source_revision"],
        "checkpoint_cursor": parent["checkpoint_cursor"], "checkpoint_sha256": parent["checkpoint_sha256"],
        "progress": progress,
        "usage": {**usage, "reported_charge_usd": None,
                  "cost_basis": "codex_subscription_charge_unreported/v1"},
        "observed_unsaved_outcomes": {"counts": counts, **coverage},
        "native_save_requested": False, "new_checkpoint_created": False,
        "new_restart_performed": False, "teardown_verified": True,
        "evidence_path": "experiments/evidence/" + filename,
    }


def save_acceptance(root: Path, filename: str, failures: list[dict]) -> dict:
    source = _read(root, filename)
    failure = next((row for row in failures if row["failure_id"] == source["parent_failure_record"]), None)
    if failure is None:
        raise ValueError("Save acceptance has no published failure")
    _matches(source, {
        "schema_version": "fortgym.native-status-stack-acceptance-summary/v1",
        "status": "native_save_reload_verified", "snapshot_profile": "native_menu_preserving_save/v4",
        "independent_audit_passed": True,
    })
    _hash(source["source_revision"], 40)
    _hash(source["independent_audit_sha256"], 64)
    _matches(source["parent_checkpoint"], {
        "cursor": failure["checkpoint_cursor"], "sha256": failure["checkpoint_sha256"], "unchanged": True,
    })
    _matches(source["reproduction"], {
        "legacy_profile": "native_menu_preserving_save/v3", "legacy_rejected_before_save": True,
        "screen_type": "<type: viewscreen>", "screen_focus": "dfhack/lua/status_overlay",
    })
    accepted = source["acceptance"]
    _matches(accepted, {
        "save_verified": True, "fresh_reload_verified": True, "world_observations_unchanged": True,
        "full_stack_identity_unchanged": True, "outer_screen_unchanged": True,
        "native_save_calls": 1, "gameplay_ticks": 0, "model_calls": 0,
        "private_food_measurement": False, "teardown_verified": True,
        "menu_navigation_keys": ["LEAVESCREEN_ALL", "D_STATUS", "CURSOR_RIGHT", "SELECT"],
    })
    _numbers(accepted, ("year", "year_tick"))
    _matches(source["campaign"], {
        "new_checkpoint_created": False, "new_restart_performed": False,
        "last_verified_checkpoint_cursor": failure["checkpoint_cursor"],
        "retained_elapsed_ticks": failure["progress"]["checkpointed_elapsed_ticks"],
        "accounted_model_responses": failure["progress"]["accounted_model_responses"],
        "unsaved_window_o_ticks": failure["progress"]["unsaved_new_native_ticks"],
        "campaign_tokens": failure["usage"]["campaign_tokens"],
        "all_attempt_tokens": failure["usage"]["all_attempt_tokens"],
        "year_two_reached": False, "sustainability": "not_established",
    })
    _matches(source["cost"], {"metered_inference_charge_usd": "0", "other_cost_usd": None})
    return {
        "acceptance_id": filename.removesuffix(".json"),
        "original_failure": failure["failure_id"], "source_revision": source["source_revision"],
        "snapshot_profile": source["snapshot_profile"], "save_verified": True,
        "fresh_reload_verified": True, "full_stack_identity_unchanged": True,
        "world_observations_unchanged": True, "teardown_verified": True,
        "model_calls": 0, "gameplay_ticks": 0, "menu_navigation_keys": 4,
        "new_campaign_checkpoint_created": False,
        "evidence_path": "experiments/evidence/" + filename,
    }
