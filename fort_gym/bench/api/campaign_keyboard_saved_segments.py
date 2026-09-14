"""Saved progress inside a failed multi-segment window, without promoting the window."""

from pathlib import Path

from .campaign_keyboard_presave import _hash, _matches, _numbers, _read

SAVED_SEGMENTS = ("astra_native_keyboard_saved_segment_20260909w.json",)
PROGRESS = (
    "parent_checkpoint_cursor", "checkpoint_cursor", "parent_elapsed_ticks",
    "saved_elapsed_ticks", "new_saved_ticks", "new_model_responses",
    "cumulative_model_responses", "loss_records", "known_lost_ticks",
)


def saved_segment(root: Path, filename: str, parents: list[dict], trials: list[dict]) -> dict:
    source = _read(root, filename)
    candidates = [row for row in parents
                  if row["checkpoint_sha256"] == source.get("parent_checkpoint_sha256")]
    previous = [row for row in trials if row["trial_id"] == source.get("previous_trial")]
    if len(candidates) != 1 or len(previous) != 1:
        raise ValueError("Saved segment requires its unique saved parent and prior trial")
    parent, prior = candidates[0], previous[0]
    if prior["parent_record"] != parent["resumed_id"]:
        raise ValueError("Saved segment prior trial belongs to another saved parent")
    _matches(source, {
        "schema_version": "fortgym.native-keyboard-saved-segment-summary/v1",
        "status": "saved_segment_in_failed_window",
        "model": "gpt-6-astra", "reasoning_effort": "medium",
        "control_profile": "native_keyboard/v2", "observation_profile": "native_screen_text/v1",
        "prompt_profile": "native_keyboard_memory_replacement/v1",
        "captured_screen_size": [120, 40], "snapshot_profile": "native_menu_preserving_save/v4",
        **{key: True for key in (
            "checkpoint_verified", "fresh_checkpoint_load_verified", "teardown_verified",
            "independent_audit_passed", "all_usage_retained", "saved_memory_retained",
        )},
        **{key: False for key in (
            "window_completed", "historical_failure_reclassified", "actions_replayed",
            "sustainability_established", "year_two_success", "matched_comparison",
            "loss_ticks_complete",
        )},
    })
    for key in ("checkpoint_sha256", "checkpoint_file_sha256", "independent_audit_sha256"):
        _hash(source.get(key), 64)
    _hash(source.get("source_revision"), 40)
    p = _numbers(source.get("progress", {}), PROGRESS)
    usage = _numbers(source.get("usage", {}), (
        "new_tokens", "campaign_tokens", "all_attempt_tokens", "historical_failed_delivery_tokens",
    ))
    _matches(source["usage"], {
        "reported_charge_usd": None, "cost_basis": "codex_subscription_charge_unreported/v1",
    })
    before = parent["progress"]
    if (
        any(value > 2**53 - 1 for value in (*p.values(), *usage.values()))
        or not 1 <= p["new_model_responses"] <= 64
        or p["parent_checkpoint_cursor"] != parent["checkpoint_cursor"]
        or p["checkpoint_cursor"] != parent["checkpoint_cursor"] + p["new_model_responses"]
        or source["checkpoint_sha256"] == parent["checkpoint_sha256"]
        or p["parent_elapsed_ticks"] != before["retained_elapsed_ticks"]
        or p["saved_elapsed_ticks"] != p["parent_elapsed_ticks"] + p["new_saved_ticks"]
        or p["new_saved_ticks"] > 2000 * p["new_model_responses"]
        or p["saved_elapsed_ticks"] >= 403200
        or p["cumulative_model_responses"] != prior["usage"]["campaign_responses"] + p["new_model_responses"]
        or p["loss_records"] != prior["progress"]["existing_loss_records"] + 1
        or p["known_lost_ticks"] != (
            prior["progress"]["existing_known_lost_ticks"] + prior["progress"]["new_committed_unsaved_ticks"]
        )
        or usage["new_tokens"] < 1
        or any(usage[key] != prior["usage"][key] + usage["new_tokens"]
               for key in ("campaign_tokens", "all_attempt_tokens"))
        or usage["historical_failed_delivery_tokens"] != parent["usage"]["historical_failed_delivery_tokens"]
        or usage["all_attempt_tokens"] != usage["campaign_tokens"] + usage["historical_failed_delivery_tokens"]
    ):
        raise ValueError("Saved segment progress, prior losses and usage do not reconcile")
    terminal = {
        "status": "failed", "phase": "second_segment_before_model_request",
        "error": "Cannot fork", "read_attempts": 3, "underlying_resource_cause": "unverified",
        "container_oom_killed": False, "second_segment_model_requests": 0,
        "second_segment_trace_and_usage_unchanged": True, "second_segment_final_clock": None,
    }
    _matches(source.get("window_outcome", {}), terminal)
    observed = source.get("saved_observation", {})
    _matches(observed, {"food_stock": None, "food_measurement_available": False})
    counts = _numbers(observed, (
        "population", "recorded_dead_citizens", "drink_stock", "completed_farms",
        "planned_unfinished_farms", "completed_beds", "completed_workshops",
    ))
    if any(value > 2**53 - 1 for value in counts.values()):
        raise ValueError("Saved segment observation counter is invalid")
    return {
        "saved_segment_id": filename.removesuffix(".json"),
        "previous_trial": prior["trial_id"], "parent_record": parent["resumed_id"],
        "source_revision": source["source_revision"], "status": source["status"],
        "checkpoint_sha256": source["checkpoint_sha256"], "progress": p,
        "checkpoint_verified": True, "fresh_checkpoint_load_verified": True,
        "teardown_verified": True, "window_completed": False,
        "loss_ticks_complete": False, "year_two_success": False,
        "sustainability_established": False, "matched_comparison": False,
        "saved_observation": {**counts, "food_stock": None, "food_measurement_available": False},
        "window_outcome": terminal,
        "usage": {**usage, "reported_charge_usd": None, "cost_basis": source["usage"]["cost_basis"]},
        "evidence_path": "experiments/evidence/" + filename,
    }
