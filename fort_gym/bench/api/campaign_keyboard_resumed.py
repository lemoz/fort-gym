"""Completed native play after a restart whose lost terminal time is unknown."""

from pathlib import Path

from .campaign_food_outcomes import food_inventory_outcome
from .campaign_keyboard_continuations import _execution_counts, _outcome_counts
from .campaign_keyboard_presave import _hash, _matches, _numbers, _read

RESUMED_WINDOWS = ("astra_native_keyboard_unavailable_restart_20260909.json",)
PROGRESS = (
    "parent_checkpoint_cursor", "checkpoint_cursor", "new_model_calls", "new_accepted_decisions",
    "cumulative_model_responses", "new_elapsed_ticks", "retained_elapsed_ticks",
    "native_save_loss_restarts", "confirmed_discarded_native_ticks",
)
USAGE = ("new_tokens", "campaign_tokens", "all_attempt_tokens", "historical_failed_delivery_tokens")
DIGESTS = (
    "independent_audit_sha256", "gameplay_review_sha256", "food_review_sha256",
    "usage_review_sha256", "clock_review_sha256", "terminal_observation_warning_sha256",
    "restart_record_sha256", "trace_sha256", "checkpoint_sha256",
)


def resumed_window(root: Path, filename: str, parents: list[dict]) -> dict:
    """Reconcile a saved window with its failed parent without inventing lost time."""
    source = _read(root, filename)
    parent = next((row for row in parents if row["failure_id"] == source.get("parent_record")), None)
    if parent is None:
        raise ValueError("Resumed window requires its recorded failed parent")
    _matches(source, {
        "schema_version": "fortgym.native-keyboard-resumed-summary/v1",
        "status": "completed", "model": "gpt-6-astra", "reasoning_effort": "medium",
        "control_profile": "native_keyboard/v2", "observation_profile": "native_screen_text/v1",
        "snapshot_profile": "native_menu_preserving_save/v4", "captured_screen_size": [120, 40],
        "parent_checkpoint_cursor": parent["checkpoint_cursor"],
        "parent_checkpoint_sha256": parent["checkpoint_sha256"],
        "discarded_native_ticks": None, "discarded_native_ticks_complete": False,
        "new_lost_uncommitted_ticks": None, "reported_charge_usd": None,
        "cost_basis": "codex_subscription_charge_unreported/v1",
        **{key: True for key in (
            "independent_retained_evidence_audit_passed", "teardown_verified",
            "parent_checkpoint_fresh_native_reload_verified", "original_checkpoint_unchanged",
            "all_prior_usage_retained", "checkpoint_memory_preserved",
            "inherited_discontinuities_unchanged", "new_restart_performed",
        )},
        **{key: False for key in (
            "uninterrupted_campaign", "actions_replayed", "strategy_intervention", "reset_memory",
            "reset_usage", "historical_failed_run_reclassified_as_success",
            "final_checkpoint_fresh_reload_verified", "live_tracking",
        )},
    })
    _hash(source.get("source_revision"), 40)
    for key in DIGESTS:
        _hash(source.get(key), 64)
    progress, usage = _numbers(source, PROGRESS), _numbers(source, USAGE)
    previous = parent["progress"]
    if (
        any(value > 2**53 - 1 for value in (*progress.values(), *usage.values()))
        or not 1 <= progress["new_model_calls"] <= 64
        or progress["new_accepted_decisions"] > progress["new_model_calls"]
        or progress["checkpoint_cursor"] != parent["checkpoint_cursor"] + progress["new_model_calls"]
        or source["checkpoint_sha256"] == parent["checkpoint_sha256"]
        or progress["cumulative_model_responses"]
        != previous["accounted_responses"] + progress["new_model_calls"]
        or progress["retained_elapsed_ticks"]
        != previous["checkpointed_elapsed_ticks"] + progress["new_elapsed_ticks"]
        or progress["new_elapsed_ticks"] > 2000 * progress["new_accepted_decisions"]
        or progress["native_save_loss_restarts"] != previous["existing_loss_records"] + 1
        or progress["confirmed_discarded_native_ticks"]
        != previous["existing_lost_ticks"] + previous["new_committed_unsaved_ticks"]
        or previous["uncommitted_elapsed_ticks"] is not None
        or usage["new_tokens"] < 1
        or any(usage[key] != parent["usage"][key] + usage["new_tokens"]
               for key in ("campaign_tokens", "all_attempt_tokens"))
        or usage["historical_failed_delivery_tokens"]
        != parent["usage"]["historical_failed_delivery_tokens"]
        or usage["all_attempt_tokens"] != usage["campaign_tokens"] + usage["historical_failed_delivery_tokens"]
    ):
        raise ValueError("Resumed window checkpoint, usage or loss history does not reconcile")
    warning = {
        "operator_status": "completed_with_warning", "native_window_status": "completed",
        "kind": "terminal_container_observation_error", "command_exit_code": 1,
        "underlying_cause": "unverified", "original_error_retained": True,
    }
    _matches(source.get("operator_observation_warning"), warning)
    outcomes = _outcome_counts(source.get("outcome_counts"), progress["new_model_calls"])
    execution = _execution_counts(source.get("execution_counts"), progress, outcomes)
    food = food_inventory_outcome(source, progress["new_model_calls"], parent["checkpoint_cursor"])
    if outcomes is None or execution is None or food is None:
        raise ValueError("Resumed window requires its reviewed gameplay measurements")
    return {
        "resumed_id": filename.removesuffix(".json"), "parent_record": parent["failure_id"],
        "source_revision": source["source_revision"], "checkpoint_cursor": progress["checkpoint_cursor"],
        "checkpoint_sha256": source["checkpoint_sha256"],
        "checkpoints": [{"cursor": progress["checkpoint_cursor"],
                         "elapsed_native_ticks": progress["retained_elapsed_ticks"],
                         "sha256": source["checkpoint_sha256"],
                         "parent_sha256": parent["checkpoint_sha256"], "checkpoint_verified": True}],
        "progress": {**progress, "discarded_native_ticks": None, "discarded_native_ticks_complete": False},
        "usage": {**usage, "reported_charge_usd": None, "cost_basis": source["cost_basis"]},
        "new_restart_performed": True, "final_checkpoint_fresh_reload_verified": False,
        "teardown_verified": True, "operator_observation_warning": warning,
        "outcome_counts": outcomes, "execution_counts": execution, "food_inventory": food,
        "evidence_path": "experiments/evidence/" + filename,
    }
