"""Later checkpoint verification, never a new gameplay window or changed history."""

from datetime import date
from pathlib import Path
import re

from .campaign_keyboard_presave import _hash, _matches, _read
from .campaign_keyboard_windows import _counts

CHECKPOINT_RELOAD_REVISIONS = {
    "astra_native_keyboard_checkpoint903_reload_20260910.json":
        "4980cdd5e8c1961772f839eeaa848d196672ed6f",
    "astra_native_keyboard_checkpoint929_reload_20260910.json":
        "b1a73c746621f17e38b08fca061b1799c6a7025d",
    "astra_native_keyboard_checkpoint1057_reload_20260910.json":
        "a542b0b732b2e59fe316b68d8140dd21bb9ecc39",
}
CHECKPOINT_RELOADS = tuple(CHECKPOINT_RELOAD_REVISIONS)


def _production_measurement(value: object) -> dict:
    """Project verified raw inputs, never completed production or private inventory."""
    if not isinstance(value, dict):
        raise ValueError("Production verification must be an object")
    flags = {
        "schema_version": "fortgym.native-production-input-verification/v1",
        "hook_profile": "fortgym.campaign-production-inputs/v2",
        "independent_inventory_scan_verified": True,
        "ownership_accessibility_assessed": False,
        "completed_brewing_measured": False,
        "original_observation_unchanged": True,
    }
    _matches(value, flags)
    counts = _counts(value, (
        "brewable_plant_stacks", "brewable_plant_stacks_in_jobs", "brewable_plant_units",
        "observed_plant_records", "old_reported_brewable_plant_units",
        "old_false_negative_item_count",
    ))
    if (counts["brewable_plant_stacks"] + counts["brewable_plant_stacks_in_jobs"]
            > counts["observed_plant_records"]
            or counts["old_false_negative_item_count"] > counts["observed_plant_records"]):
        raise ValueError("Production verification counts exceed observed records")
    reproduced = counts["old_false_negative_item_count"] > 0
    _matches(value, {"old_false_negative_reproduced": reproduced})
    tokens = value.get("material_tokens")
    if (not isinstance(tokens, list) or len(tokens) > 64
            or any(not isinstance(token, str) or not re.fullmatch(r"[A-Z0-9_]{1,96}", token)
                   for token in tokens)
            or len(set(tokens)) != len(tokens)
            or (counts["observed_plant_records"] > 0 and not tokens)):
        raise ValueError("Production verification material tokens are invalid")
    return {**flags, **counts, "material_tokens": tokens,
            "old_false_negative_reproduced": reproduced}


def checkpoint_reload(root: Path, filename: str, parents: list[dict]) -> dict:
    source = _read(root, filename)
    _hash(source.get("checkpoint_sha256"), 64)
    candidates = [row for row in parents
                  if row["checkpoint_sha256"] == source["checkpoint_sha256"]]
    if len(candidates) != 1:
        raise ValueError("Checkpoint reload requires one matching saved parent")
    parent = candidates[0]
    progress, usage = parent["progress"], parent["usage"]
    _matches(source, {
        "schema_version": "fortgym.native-keyboard-checkpoint-reload-summary/v1",
        "campaign_model": parent["model"], "campaign_reasoning_effort": parent["reasoning_effort"],
        "control_profile": "native_keyboard/v2", "observation_profile": "native_screen_text/v1",
        "runtime_rpc_transport": "native-rpc", "actual_screen_size": [120, 40],
        "checkpoint_cursor": progress["checkpoint_cursor"],
        "retained_elapsed_native_ticks": progress["saved_elapsed_ticks"],
        "cumulative_campaign_responses": progress["cumulative_model_responses"],
        "campaign_tokens": usage["campaign_tokens"],
        "historical_loss_records_preserved": progress["loss_records"],
        "known_lost_ticks_preserved": progress["known_lost_ticks"], "total_lost_ticks": None,
        "reported_campaign_charge_usd": None,
        "cost_basis": "codex_subscription_charge_unreported/v1",
        **{key: 0 for key in (
            "model_calls_to_reload", "new_model_tokens", "native_gameplay_keys_to_reload",
            "requested_native_ticks", "observed_new_native_ticks", "native_saves_requested",
            "cloud_vms_created", "guest_poweroff_returncode", "vm_stop_returncode",
        )},
        **{key: True for key in (
            "fresh_native_reload_verified", "normal_campaign_loop_restored",
            "model_memory_configuration_usage_unchanged", "trace_and_usage_journals_byte_identical",
            "recorded_observations_equal_before_after", "original_checkpoint_unchanged",
            "independent_retained_evidence_audit_passed", "native_cleanup_verified",
            "container_teardown_verified", "vm_observed_stopped",
        )},
        **{key: False for key in (
            "new_checkpoint_created", "disposable_save_tree_byte_identical",
            "autonomous_gameplay", "year_two_success", "sustainable_fortress_verified",
            "cross_model_comparison",
        )},
    })
    _hash(source.get("source_revision"), 40)
    for key in ("audit_sha256", "fixture_sha256", "owner_receipt_sha256", "native_reload_receipt_sha256"):
        _hash(source.get(key), 64)
    recorded = source.get("recorded_date_utc")
    if not isinstance(recorded, str) or date.fromisoformat(recorded).isoformat() != recorded:
        raise ValueError("Checkpoint reload date must be an ISO date")
    calendar = _counts(source.get("native_calendar"), ("year", "year_tick"))
    _matches(source["native_calendar"], {"paused": True})
    if calendar["year_tick"] >= 403200:
        raise ValueError("Checkpoint reload calendar is invalid")
    delta = source.get("disposable_save_tree_difference")
    if not isinstance(delta, dict):
        raise ValueError("Checkpoint reload file changes must be an object")
    _matches(delta, {"path": "events-dfhack.log", "world_sav_unchanged": True,
                     "change": "Two appended world/map-loaded log lines; original prefix preserved"})
    delta_counts = _counts(delta, ("bytes_before", "bytes_after", "other_files_unchanged"))
    if delta_counts["bytes_after"] <= delta_counts["bytes_before"]:
        raise ValueError("Checkpoint reload must retain its observed event-log append")
    production = ({"production_measurement": _production_measurement(source["production_measurement"])}
                  if "production_measurement" in source else {})
    return {
        "verification_id": filename.removesuffix(".json"), "recorded_only": True,
        "parent_record": parent["window_id"], "checkpoint_sha256": parent["checkpoint_sha256"],
        "checkpoint_cursor": progress["checkpoint_cursor"],
        "saved_elapsed_ticks": progress["saved_elapsed_ticks"],
        "source_revision": source["source_revision"], "recorded_date_utc": recorded,
        "actual_screen_size": [120, 40], "native_calendar": {**calendar, "paused": True},
        "fresh_native_reload_verified": True, "normal_campaign_loop_restored": True,
        "original_checkpoint_unchanged": True, "agent_history_usage_unchanged": True,
        "model_calls": 0, "new_tokens": 0, "new_game_ticks": 0, "new_checkpoint_created": False,
        "gameplay_result": False, "teardown_verified": True,
        "disposable_save_tree_byte_identical": False,
        "disposable_save_tree_difference": {"path": "events-dfhack.log", **delta_counts,
                                            "world_sav_unchanged": True},
        "evidence_path": "experiments/evidence/" + filename,
        "evidence_revision": CHECKPOINT_RELOAD_REVISIONS[filename],
        **production,
    }
