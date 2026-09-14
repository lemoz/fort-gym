"""Recorded dialog trials, preserving infrastructure failure and unknown time."""

from pathlib import Path

from .campaign_keyboard_presave import _hash, _matches, _numbers, _read

MODAL_TRIALS = ("astra_native_keyboard_modal_trial_20260909.json",)
COUNTERS = (
    "parent_checkpoint_cursor", "checkpointed_elapsed_ticks", "new_responses",
    "committed_trace_decisions", "committed_trace_cursor", "new_committed_unsaved_ticks",
    "final_uncommitted_decisions", "final_input_keys_confirmed", "final_requested_advance_ticks",
    "native_modal_deferrals_verified", "memory_clears", "existing_loss_records",
    "existing_known_lost_ticks",
)


def modal_trial(root: Path, filename: str, parents: list[dict], prior_trials: list[dict]) -> dict:
    source = _read(root, filename)
    matches = [row for row in parents
               if row["checkpoint_sha256"] == source.get("parent_checkpoint_sha256")]
    if len(matches) != 1:
        raise ValueError("Dialog trial requires its unique recorded saved parent")
    parent = matches[0]
    previous = [row for row in prior_trials if row["parent_record"] == parent["resumed_id"]]
    if len(previous) != 1:
        raise ValueError("Dialog trial requires its unique previous unsaved prompt trial")
    prior = previous[0]
    _matches(source, {
        "schema_version": "fortgym.native-keyboard-modal-trial-summary/v1",
        "status": "failed", "model": "gpt-6-astra", "reasoning_effort": "medium",
        "control_profile": "native_keyboard/v2", "observation_profile": "native_screen_text/v1",
        "prompt_profile": "native_keyboard_memory_replacement/v1",
        "terminal_reason": "host_read_exit_128_then_owned_termination",
        "underlying_read_failure_cause": "unverified_output_not_retained",
        "parent_checkpoint_cursor": parent["checkpoint_cursor"],
        "final_uncommitted_ticks": None, "final_elapsed_ticks_complete": False,
        **{key: True for key in (
            "integrity_audit_passed", "teardown_verified", "parent_checkpoint_unchanged",
            "parent_native_load_verified", "model_selected_continuation_after_deferrals_verified",
        )},
        **{key: False for key in (
            "container_oom_killed", "new_checkpoint_verified", "existing_loss_ticks_complete",
            "sustainability_established", "year_two_success", "matched_comparison",
            "gameplay_collapse_established",
        )},
    })
    _hash(source.get("source_revision"), 40)
    _hash(source.get("independent_audit_sha256"), 64)
    numbers = _numbers(source, COUNTERS)
    p, previous_progress = parent["progress"], prior["progress"]
    usage_source = source.get("usage")
    if not isinstance(usage_source, dict):
        raise ValueError("Dialog trial usage is missing")
    usage = _numbers(usage_source, (
        "new_tokens", "campaign_responses", "campaign_tokens", "all_attempt_tokens",
        "historical_failed_delivery_tokens",
    ))
    _matches(usage_source, {
        "reported_charge_usd": None, "cost_basis": "codex_subscription_charge_unreported/v1",
    })
    if (
        any(value > 2**53 - 1 for value in (*numbers.values(), *usage.values()))
        or not 1 <= numbers["new_responses"] <= 64
        or numbers["new_responses"] != numbers["committed_trace_decisions"] + 1
        or numbers["final_uncommitted_decisions"] != 1
        or numbers["committed_trace_cursor"] != parent["checkpoint_cursor"] + numbers["committed_trace_decisions"]
        or numbers["checkpointed_elapsed_ticks"] != p["retained_elapsed_ticks"]
        or numbers["new_committed_unsaved_ticks"] > numbers["committed_trace_decisions"] * 2000
        or not 1 <= numbers["native_modal_deferrals_verified"] <= numbers["committed_trace_decisions"]
        or not 1 <= numbers["final_input_keys_confirmed"] <= 32
        or numbers["final_requested_advance_ticks"] != 0
        or numbers["memory_clears"] > numbers["new_responses"]
        or numbers["existing_loss_records"] != previous_progress["existing_loss_records"] + 1
        or numbers["existing_known_lost_ticks"] != (
            previous_progress["existing_known_lost_ticks"]
            + previous_progress["new_committed_unsaved_ticks"] + previous_progress["uncommitted_ticks"]
        )
        or usage["new_tokens"] < 1
        or usage["campaign_responses"] != (
            p["cumulative_model_responses"] + previous_progress["new_responses"] + numbers["new_responses"]
        )
        or any(usage[key] != prior["usage"][key] + usage["new_tokens"]
               for key in ("campaign_tokens", "all_attempt_tokens"))
        or usage["historical_failed_delivery_tokens"] != parent["usage"]["historical_failed_delivery_tokens"]
    ):
        raise ValueError("Dialog trial progress and usage do not reconcile with earlier attempts")
    observed = source.get("last_unsaved_observation")
    if not isinstance(observed, dict) or observed.get("food_stock", "missing") is not None:
        raise ValueError("Dialog trial must retain its unmeasured food inventory")
    counts = _numbers(observed, (
        "population", "recorded_dead_citizens", "drink_stock",
        "completed_workshops", "completed_beds", "completed_farms",
    ))
    if any(value > 2**53 - 1 for value in counts.values()):
        raise ValueError("Invalid dialog trial observation")
    return {
        "trial_id": filename.removesuffix(".json"), "parent_record": parent["resumed_id"],
        "previous_trial": prior["trial_id"], "source_revision": source["source_revision"],
        "status": "failed", "terminal_reason": source["terminal_reason"],
        "underlying_read_failure_cause": source["underlying_read_failure_cause"],
        "progress": {**numbers, "final_uncommitted_ticks": None, "final_elapsed_ticks_complete": False},
        "last_unsaved_observation": {**counts, "food_stock": None},
        "usage": {**usage, "reported_charge_usd": None, "cost_basis": usage_source["cost_basis"]},
        "teardown_verified": True, "new_checkpoint_verified": False,
        "matched_comparison": False, "sustainability_established": False, "year_two_success": False,
        "evidence_path": "experiments/evidence/" + filename,
    }
