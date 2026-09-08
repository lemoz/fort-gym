"""Project authored restart evidence without exposing private gameplay content."""

import json
import re
from pathlib import Path

RESTARTS = ("astra_native_keyboard_restart_20260908.json",)
PRESAVE_RESTARTS = ("astra_native_keyboard_presave_restart_20260908.json",)
CHECKPOINT_REVIEWS = (
    "astra_native_keyboard_checkpoint_review_20260908.json",
    "astra_native_keyboard_menu_identity_review_20260908.json",
)


def keyboard_restart(root: Path, filename: str, failures: list[dict], recoveries: list[dict]) -> dict:
    path = root / "experiments/evidence" / filename
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise ValueError("Restart evidence must be a bounded regular publication")
    source = json.loads(path.read_bytes())
    presave = source.get("schema_version") == "fortgym.native-keyboard-restart-summary/v2"
    identities = {
        "schema_version": f"fortgym.native-keyboard-restart-summary/v{2 if presave else 1}",
        "model": "gpt-6-astra",
        "reasoning_effort": "medium",
        "control_profile": "native_keyboard/v2",
        "observation_profile": "native_screen_text/v1",
        "snapshot_profile": f"native_menu_preserving_save/v{4 if presave else 1}",
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
    if presave:
        if (
            "continuation_id" not in parent or failure.get("parent_record") != parent["continuation_id"]
            or source.get("captured_screen_size") != [120, 40]
            or type(source.get("steps_per_segment")) is not int
            or not 1 <= source["steps_per_segment"] <= 64
            or source["steps_per_segment"] != progress["new_model_responses"]
            or source.get("save_failure_stage") != "identity_before_save"
            or source.get("final_checkpoint_fresh_reload_verified") is not False
            or type(source.get("native_save_loss_restarts")) is not int
            or source["native_save_loss_restarts"] != parent["progress"]["native_save_loss_restarts"] + 1
            or any(not isinstance(source.get(key), str) or re.fullmatch("[a-f0-9]{64}", source[key]) is None
                   for key in ("independent_audit_sha256", "source_save_attempt_sha256"))
        ):
            raise ValueError("Pre-save restart must retain its failure stage and inherited losses")
        failed_cursor = failure["checkpoint_cursor"]
        prior_responses = old_progress["accounted_model_responses"]
        prior_ticks = parent["progress"]["retained_elapsed_ticks"]
        total_loss = parent["progress"]["discarded_native_ticks"] + old_progress["unsaved_new_native_ticks"]
        failed_delivery_tokens = old_usage["all_attempt_tokens"] - old_usage["campaign_tokens"]
    else:
        failed_cursor = old_progress["last_resumable_checkpoint_cursor"]
        prior_responses = old_progress["returned_model_responses"]
        prior_ticks = parent["elapsed_native_ticks"]
        total_loss = old_progress["unsaved_new_native_ticks"]
        failed_delivery_tokens = old_usage["historical_failed_delivery_tokens"]
    if (
        progress["restored_checkpoint_cursor"] != parent["checkpoint_cursor"]
        or progress["restored_checkpoint_cursor"] != failed_cursor
        or source["checkpoint_sha256"] == source["parent_checkpoint_sha256"]
        or progress["new_model_responses"] <= 0
        or progress["new_accepted_decisions"] > progress["new_model_responses"]
        or progress["checkpoint_cursor"]
        != progress["restored_checkpoint_cursor"] + progress["new_model_responses"]
        or progress["cumulative_model_responses"]
        != prior_responses + progress["new_model_responses"]
        or progress["retained_elapsed_ticks"]
        != prior_ticks + progress["new_elapsed_ticks"]
        or progress["discarded_native_ticks"] != total_loss
        or usage["new_tokens"] <= 0
        or usage["campaign_tokens"] != old_usage["campaign_tokens"] + usage["new_tokens"]
        or usage["all_attempt_tokens"] != old_usage["all_attempt_tokens"] + usage["new_tokens"]
        or usage["lost_tail_tokens_retained"] != old_usage["new_tokens"]
        or usage["historical_failed_delivery_tokens"] != failed_delivery_tokens
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
        **({"recent_event": True, "snapshot_profile": source["snapshot_profile"],
            "native_save_loss_restarts": source["native_save_loss_restarts"],
            "final_checkpoint_fresh_reload_verified": False} if presave else {}),
        "fortress_success": "not_assessed_in_public_operational_summary",
        "evidence_path": "experiments/evidence/" + filename,
    }


def checkpoint_review(
    root: Path, filename: str, restarts: list[dict], recoveries: list[dict] | None = None,
) -> dict:
    """Keep a copied-but-unverified save distinct from proven loss or recovery."""
    path = root / "experiments/evidence" / filename
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise ValueError("Checkpoint review must be a bounded regular publication")
    source = json.loads(path.read_bytes())
    identity_failure = source.get("terminal_reason") == "native_menu_identity_changed_during_save"
    if identity_failure:
        recovery = next((row for row in recoveries or []
                         if row["recovery_id"] == source.get("parent_recovery")), None)
        parent = None if recovery is None or "parent_restart" in source else {
            "checkpoint_sha256": recovery["checkpoint_sha256"],
            "progress": {
                "checkpoint_cursor": recovery["checkpoint_cursor"],
                "retained_elapsed_ticks": recovery["elapsed_native_ticks"],
                "cumulative_model_responses": recovery["returned_model_decisions"],
            },
            "usage": recovery["usage"],
        }
    else:
        parent = next((row for row in restarts
                       if row["restart_id"] == source.get("parent_restart")), None)
        if "parent_recovery" in source:
            parent = None
    save_proof = ("native_save_retained_in_runtime", "world_save_differs_from_parent",
                  "recorded_world_observations_unchanged_during_save") if identity_failure else (
                      "copied_native_save_matches_runtime", "copied_world_save_differs_from_parent",
                  )
    if (
        parent is None
        or source["schema_version"] != "fortgym.native-keyboard-checkpoint-review/v1"
        or source["terminal_reason"] not in {
            "native_screen_changed_during_save", "native_menu_identity_changed_during_save",
        }
        or (identity_failure and (
            source.get("snapshot_profile") != "native_menu_preserving_save/v2"
            or source.get("rejected_operation_receipt_retained") is not False
            or source.get("specific_changed_ui_field", "missing") is not None
        ))
        or re.fullmatch("[a-f0-9]{40}", source["source_revision"]) is None
        or source["parent_checkpoint_sha256"] != parent["checkpoint_sha256"]
        or source["checkpoint_verified"] is not False
        or any(source[key] is not True for key in (
            "independent_retained_evidence_audit_passed", *save_proof,
            "new_native_state_requires_reload_verification",
            "original_checkpoint_and_trace_prefix_unchanged", "inherited_discontinuity_unchanged",
            "teardown_verified",
        ))
    ):
        raise ValueError("Checkpoint review provenance is inconsistent")
    progress = {key: source["progress"][key] for key in (
        "trace_cursor", "latest_verified_checkpoint_cursor", "new_accepted_decisions",
        "cumulative_model_responses", "new_elapsed_ticks", "trace_elapsed_ticks",
        "last_verified_elapsed_ticks",
    )}
    usage = {key: source["usage"][key] for key in ("new_tokens", "campaign_tokens", "all_attempt_tokens")}
    if any(type(value) is not int or value < 0 for value in (*progress.values(), *usage.values())):
        raise ValueError("Checkpoint review counters are invalid")
    previous = parent["progress"]
    if (
        progress["latest_verified_checkpoint_cursor"] != previous["checkpoint_cursor"]
        or progress["last_verified_elapsed_ticks"] != previous["retained_elapsed_ticks"]
        or progress["new_accepted_decisions"] <= 0
        or progress["trace_cursor"]
        != previous["checkpoint_cursor"] + progress["new_accepted_decisions"]
        or progress["cumulative_model_responses"]
        != previous["cumulative_model_responses"] + progress["new_accepted_decisions"]
        or progress["trace_elapsed_ticks"]
        != previous["retained_elapsed_ticks"] + progress["new_elapsed_ticks"]
        or usage["new_tokens"] <= 0
        or usage["campaign_tokens"] != parent["usage"]["campaign_tokens"] + usage["new_tokens"]
        or usage["all_attempt_tokens"] != parent["usage"]["all_attempt_tokens"] + usage["new_tokens"]
        or source["usage"]["reported_charge_usd"] is not None
        or source["usage"]["cost_basis"] != "codex_subscription_charge_unreported/v1"
    ):
        raise ValueError("Checkpoint review must retain all newer progress and usage")
    return {
        "review_id": filename.removesuffix(".json"),
        "parent_checkpoint_sha256": source["parent_checkpoint_sha256"],
        "source_revision": source["source_revision"],
        **({"parent_recovery": source["parent_recovery"]} if identity_failure else
           {"parent_restart": source["parent_restart"]}),
        "terminal_reason": source["terminal_reason"],
        "progress": progress,
        "usage": {**usage, "reported_charge_usd": None,
                  "cost_basis": "codex_subscription_charge_unreported/v1"},
        "checkpoint_verified": False,
        "new_native_state_requires_reload_verification": True,
        "teardown_verified": True,
        "evidence_path": "experiments/evidence/" + filename,
    }
