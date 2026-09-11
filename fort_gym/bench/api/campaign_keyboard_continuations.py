"""Allowlisted, non-content continuations of the recovered keyboard campaign."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .campaign_food_outcomes import food_inventory_outcome

CONTINUATIONS = (
    "astra_native_keyboard_settled_play_20260908.json",
    "astra_native_keyboard_workshop_play_20260908.json",
    "astra_native_keyboard_workshop_continuation_20260908.json",
    "astra_native_keyboard_quarter_year_continuation_20260908.json",
    "astra_native_keyboard_midyear_continuation_20260908.json",
    "astra_native_keyboard_food_continuation_20260908.json",
)
# Populated only with independently audited native results, never test fixtures.
POSTRESTART_CONTINUATIONS = ("astra_native_keyboard_postrestart_continuation_20260908.json",)
IDENTITIES = {
    "status": "completed",
    "model": "gpt-6-astra",
    "reasoning_effort": "medium",
    "control_profile": "native_keyboard/v2",
    "observation_profile": "native_screen_text/v1",
    "snapshot_profile": "native_menu_preserving_save/v3",
    "cost_basis": "codex_subscription_charge_unreported/v1",
}
COUNTERS = (
    "parent_checkpoint_cursor", "new_model_calls", "new_accepted_decisions",
    "cumulative_model_responses", "new_elapsed_ticks", "retained_elapsed_ticks",
    "new_tokens", "campaign_tokens", "all_attempt_tokens", "discarded_native_ticks",
    "native_save_loss_restarts", "steps_per_segment",
)


def keyboard_continuation(root: Path, filename: str, parents: list[dict], failures: list[dict]) -> dict:
    path = root / "experiments/evidence" / filename
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise ValueError("Keyboard continuation must be a bounded regular publication")
    source = json.loads(path.read_bytes())
    warning = _operator_warning(source)
    postrestart = source.get("schema_version") == "fortgym.native-keyboard-continuation-summary/v3"
    identities = {**IDENTITIES, "snapshot_profile":
                  f"native_menu_preserving_save/v{4 if postrestart else 3}"}
    parent = next((row for row in parents
                   if row.get("continuation_id", row.get("recovery_id", row.get("restart_id")))
                   == source["parent_record"]), None)
    if (
        parent is None
        or any(source.get(key) != value for key, value in identities.items())
        or source["captured_screen_size"] != [120, 40]
        or re.fullmatch("[a-f0-9]{40}", source["source_revision"]) is None
        or source["parent_checkpoint_sha256"] != parent["checkpoint_sha256"]
        or source["reported_charge_usd"] is not None
        or any(source[key] is not True for key in (
            "independent_retained_evidence_audit_passed", "teardown_verified",
            "original_checkpoint_unchanged", "memory_and_usage_preserved_across_segments",
            "inherited_discontinuity_unchanged",
        ))
        or any(source[key] is not False for key in (
            "uninterrupted_campaign", "new_restart_performed", "strategy_intervention",
            "reset_memory", "reset_usage", "historical_failed_run_reclassified_as_success",
            "final_checkpoint_fresh_reload_verified",
        ))
    ):
        raise ValueError("Keyboard continuation provenance is inconsistent")
    counters = {key: source[key] for key in COUNTERS}
    if any(type(value) is not int or value < 0 for value in counters.values()):
        raise ValueError("Keyboard continuation counters are invalid")
    restarted = "restart_id" in parent
    continued = "continuation_id" in parent or restarted
    if postrestart and (
        not continued or parent.get("snapshot_profile") != "native_menu_preserving_save/v4"
    ):
        raise ValueError("Post-restart continuation requires a verified v4 parent")
    if not postrestart and (restarted or parent.get("snapshot_profile") == "native_menu_preserving_save/v4"):
        raise ValueError("Restart parent requires an explicit v3 continuation publication")
    parent_cursor = parent["progress"]["checkpoint_cursor"] if restarted else parent["checkpoint_cursor"]
    parent_responses = (parent["progress"]["cumulative_model_responses"] if continued
                        else parent["returned_model_decisions"])
    parent_ticks = (parent["progress"]["retained_elapsed_ticks"] if continued
                    else parent["elapsed_native_ticks"])
    prior_losses = ((parent["native_save_loss_restarts"] if restarted
                     else parent["progress"]["native_save_loss_restarts"])
                    if postrestart else len(failures))
    prior_discarded_ticks = (parent["progress"]["discarded_native_ticks"] if postrestart
                            else sum(row["progress"]["unsaved_new_native_ticks"] for row in failures))
    if (
        source["parent_checkpoint_cursor"] != parent_cursor
        or not 1 <= source["steps_per_segment"] <= 64
        or source["new_model_calls"] < 1
        or source["new_accepted_decisions"] > source["new_model_calls"]
        or source["cumulative_model_responses"]
        != parent_responses + source["new_model_calls"]
        or source["retained_elapsed_ticks"] != parent_ticks + source["new_elapsed_ticks"]
        or source["campaign_tokens"] != parent["usage"]["campaign_tokens"] + source["new_tokens"]
        or source["all_attempt_tokens"] != parent["usage"]["all_attempt_tokens"] + source["new_tokens"]
        or source["native_save_loss_restarts"] != prior_losses
        or source["discarded_native_ticks"] != prior_discarded_ticks
    ):
        raise ValueError("Continuation must preserve parent progress, usage and loss history")
    checkpoints = source["checkpoints"]
    if not isinstance(checkpoints, list) or not 1 <= len(checkpoints) <= 16:
        raise ValueError("Continuation requires bounded checkpoint coverage")
    cursor, ticks, digest = (parent_cursor, parent_ticks,
                             parent["checkpoint_sha256"])
    projected = []
    for row in checkpoints:
        if (
            type(row["cursor"]) is not int or type(row["elapsed_native_ticks"]) is not int
            or row["cursor"] != cursor + source["steps_per_segment"]
            or row["elapsed_native_ticks"] < ticks
            or re.fullmatch("[a-f0-9]{64}", row["sha256"]) is None
            or row["sha256"] == digest or row["parent_sha256"] != digest
            or row["checkpoint_verified"] is not True
        ):
            raise ValueError("Continuation checkpoint lineage does not reconcile")
        projected.append({key: row[key] for key in (
            "cursor", "elapsed_native_ticks", "sha256", "parent_sha256", "checkpoint_verified",
        )})
        cursor, ticks, digest = row["cursor"], row["elapsed_native_ticks"], row["sha256"]
    if (
        cursor != parent_cursor + source["new_model_calls"]
        or ticks != source["retained_elapsed_ticks"]
    ):
        raise ValueError("Continuation checkpoints must cover all new decisions and time")
    outcomes = _outcome_counts(source.get("outcome_counts"), source["new_model_calls"])
    food = food_inventory_outcome(source, source["new_model_calls"], parent_cursor)
    execution = _execution_counts(source.get("execution_counts"), counters, outcomes)
    return {
        "continuation_id": filename.removesuffix(".json"),
        "source_revision": source["source_revision"],
        "parent_record": source["parent_record"],
        "checkpoint_cursor": cursor,
        "checkpoint_sha256": digest,
        "checkpoints": projected,
        "progress": {key: counters[key] for key in COUNTERS if "token" not in key},
        "usage": {key: source[key] for key in (
            "new_tokens", "campaign_tokens", "all_attempt_tokens", "reported_charge_usd", "cost_basis",
        )},
        "snapshot_profile": source["snapshot_profile"],
        "teardown_verified": True,
        "final_checkpoint_fresh_reload_verified": False,
        "new_restart_performed": False,
        "uninterrupted_campaign": False,
        "fortress_success": "not_assessed_in_public_operational_summary",
        "evidence_path": "experiments/evidence/" + filename,
        **({"outcome_counts": outcomes} if outcomes is not None else {}),
        **({"food_inventory": food} if food is not None else {}),
        **({"execution_counts": execution} if execution is not None else {}),
        **({"operator_status": warning["operator_status"], "operator_observation_warning": warning}
           if warning is not None else {}),
    }


def _operator_warning(source: dict) -> dict | None:
    """Preserve native completion separately from a failed outer observation."""
    version = source.get("schema_version")
    if version == "fortgym.native-keyboard-continuation-summary/v1":
        if "operator_status" in source or "operator_observation_warning" in source:
            raise ValueError("Operator warning requires the explicit v2 publication")
        return None
    expected = {
        "operator_status": "failed", "native_window_status": "completed",
        "kind": "exchange_observation_error", "command_exit_code": 137,
        "underlying_cause": "unverified", "original_error_retained": True,
    }
    if version == "fortgym.native-keyboard-continuation-summary/v3":
        if not any(key in source for key in (
            "operator_status", "operator_observation_warning", "terminal_observation_warning_sha256",
        )):
            return None
        expected = {
            "operator_status": "completed_with_warning", "native_window_status": "completed",
            "kind": "terminal_container_observation_error", "command_exit_code": 128,
            "underlying_cause": "unverified", "original_error_retained": True,
        }
        digest = source.get("terminal_observation_warning_sha256")
        if not isinstance(digest, str) or re.fullmatch("[a-f0-9]{64}", digest) is None:
            raise ValueError("Terminal observation warning requires retained evidence")
    elif version != "fortgym.native-keyboard-continuation-summary/v2":
        raise ValueError("Unsupported keyboard continuation schema")
    value = source.get("operator_observation_warning")
    if (
        source.get("operator_status") != expected["operator_status"] or not isinstance(value, dict)
        or any(type(value.get(key)) is not type(target) or value[key] != target
               for key, target in expected.items())
    ):
        raise ValueError("Native completion must retain the audited operator warning")
    return expected


def _outcome_counts(value: object, decisions: int) -> dict | None:
    """Project authored aggregate counts, never captured game/model content."""
    if value is None:
        return None
    if not isinstance(value, dict) or (
        value.get("schema_version") != "fortgym.keyboard-outcome-counts/v1"
        or value.get("independent_private_review_passed") is not True
        or value.get("food_stock", "missing") is not None
        or value.get("production_and_consumption") != "not_measured"
        or value.get("sustainability") != "not_established"
    ):
        raise ValueError("Invalid authored outcome provenance")
    counts = {}
    source = value.get("counts")
    if not isinstance(source, dict):
        raise ValueError("Outcome counts are missing")
    for key in ("population", "completed_farms", "completed_beds", "completed_workshops",
                "recorded_dead_citizens", "drink_units"):
        row = source.get(key)
        if not isinstance(row, dict) or any(type(row.get(k)) is not int or row[k] < 0
                                            for k in ("start", "end")):
            raise ValueError("Invalid authored outcome count")
        counts[key] = {k: row[k] for k in ("start", "end")}
    time: dict[str, int] = {}
    for key in ("advancing_decisions", "zero_tick_decisions"):
        n = value.get(key)
        if type(n) is not int or n < 0:
            raise ValueError("Invalid outcome decision count")
        time[key] = n
    if sum(time.values()) != decisions:
        raise ValueError("Outcome decisions do not reconcile with this window")
    return {"counts": counts, **time, "food_stock": None,
            "production_and_consumption": "not_measured", "sustainability": "not_established"}


def _execution_counts(value: object, progress: dict, outcomes: dict | None) -> dict | None:
    """Separate actual game time from model requests and undispatched rejections."""
    if value is None:
        return None
    if not isinstance(value, dict) or outcomes is None or (
        value.get("schema_version") != "fortgym.keyboard-execution-counts/v1"
        or value.get("independent_private_review_passed") is not True
    ):
        raise ValueError("Invalid authored execution provenance")
    counts = {}
    for key in ("requested_elapsed_ticks", "model_input_rejections", "rejected_native_key_events",
                "menu_deferrals", "clock_unavailable_timeouts"):
        n = value.get(key)
        if type(n) is not int or n < 0:
            raise ValueError("Invalid authored execution count")
        counts[key] = n
    if (
        counts["requested_elapsed_ticks"] < progress["new_elapsed_ticks"]
        or counts["model_input_rejections"]
        != progress["new_model_calls"] - progress["new_accepted_decisions"]
        or counts["rejected_native_key_events"] != 0
        or counts["model_input_rejections"] + counts["menu_deferrals"]
        + counts["clock_unavailable_timeouts"] > outcomes["zero_tick_decisions"]
        or counts["menu_deferrals"] + counts["clock_unavailable_timeouts"]
        > progress["new_accepted_decisions"]
    ):
        raise ValueError("Execution counts do not reconcile with the audited window")
    return counts
