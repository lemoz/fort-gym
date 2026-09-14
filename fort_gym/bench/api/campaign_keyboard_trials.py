"""Bounded public results for explicitly versioned native prompt experiments."""

from pathlib import Path

from .campaign_keyboard_presave import _hash, _matches, _numbers, _read

PROMPT_TRIALS = ("astra_native_keyboard_memory_contract_20260909.json",)
COUNTERS = (
    "parent_checkpoint_cursor", "new_responses", "committed_decisions", "uncommitted_decisions",
    "committed_trace_cursor", "new_committed_unsaved_ticks", "uncommitted_ticks",
    "checkpointed_elapsed_ticks", "existing_loss_records", "existing_known_lost_ticks",
    "new_tokens", "campaign_tokens", "all_attempt_tokens", "historical_failed_delivery_tokens",
    "memory_clears", "advancing_decisions", "zero_tick_committed_decisions",
)


def prompt_trial(root: Path, filename: str, parents: list[dict]) -> dict:
    """Project a failed trial without promoting unsaved progress or causal claims."""
    source = _read(root, filename)
    parent = next((row for row in parents if row["resumed_id"] == source.get("parent_record")), None)
    if parent is None:
        raise ValueError("Prompt trial requires its recorded saved parent")
    _matches(source, {
        "schema_version": "fortgym.native-keyboard-prompt-trial/v1", "status": "failed",
        "model": "gpt-6-astra", "reasoning_effort": "medium",
        "control_profile": "native_keyboard/v2", "observation_profile": "native_screen_text/v1",
        "prompt_profile": "native_keyboard_memory_replacement/v1",
        "terminal_reason": "modal_clock_baseline_invalid_then_pending_save",
        "parent_checkpoint_cursor": parent["checkpoint_cursor"],
        "parent_checkpoint_sha256": parent["checkpoint_sha256"],
        "reported_charge_usd": None, "cost_basis": "codex_subscription_charge_unreported/v1",
        "food_stock": None, "sustainability": "not_established",
        **{key: True for key in (
            "integrity_audit_passed", "parent_checkpoint_unchanged", "parent_fresh_native_reload_verified",
            "memory_handoff_verified", "prompt_receipts_verified", "teardown_verified",
        )},
        **{key: False for key in (
            "new_checkpoint_created", "existing_lost_ticks_complete", "container_oom_killed",
            "model_performance_improvement_established", "matched_comparison", "year_two_success",
        )},
    })
    _hash(source.get("source_revision"), 40)
    _hash(source.get("independent_audit_sha256"), 64)
    numbers = _numbers(source, COUNTERS)
    p, u = parent["progress"], parent["usage"]
    if (
        any(value > 2**53 - 1 for value in numbers.values())
        or not 1 <= numbers["new_responses"] <= 64
        or numbers["new_responses"] != numbers["committed_decisions"] + numbers["uncommitted_decisions"]
        or numbers["uncommitted_decisions"] != 1 or numbers["uncommitted_ticks"] != 0
        or numbers["committed_trace_cursor"] != parent["checkpoint_cursor"] + numbers["committed_decisions"]
        or numbers["checkpointed_elapsed_ticks"] != p["retained_elapsed_ticks"]
        or numbers["existing_loss_records"] != p["native_save_loss_restarts"]
        or numbers["existing_known_lost_ticks"] != p["confirmed_discarded_native_ticks"]
        or numbers["new_committed_unsaved_ticks"] > numbers["advancing_decisions"] * 2000
        or numbers["advancing_decisions"] + numbers["zero_tick_committed_decisions"] != numbers["committed_decisions"]
        or numbers["memory_clears"] > numbers["new_responses"]
        or numbers["new_tokens"] < 1
        or any(numbers[key] != u[key] + numbers["new_tokens"] for key in ("campaign_tokens", "all_attempt_tokens"))
        or numbers["historical_failed_delivery_tokens"] != u["historical_failed_delivery_tokens"]
    ):
        raise ValueError("Prompt trial counters do not reconcile with the saved parent")
    if not isinstance(source.get("counts"), dict):
        raise ValueError("Prompt trial requires reviewed outcome counts")
    counts = {key: _numbers(source["counts"].get(key, {}), ("start", "end"))
              for key in ("population", "recorded_dead_citizens", "drink_units")}
    if any(value > 2**53 - 1 for pair in counts.values() for value in pair.values()):
        raise ValueError("Invalid prompt trial outcome")
    if any(pair["start"] != parent["outcome_counts"]["counts"][key]["end"]
           for key, pair in counts.items()):
        raise ValueError("Prompt trial starting outcomes differ from its saved parent")
    return {
        "trial_id": filename.removesuffix(".json"), "parent_record": parent["resumed_id"],
        "source_revision": source["source_revision"], "status": "failed",
        "prompt_profile": source["prompt_profile"], "terminal_reason": source["terminal_reason"],
        "progress": numbers, "counts": counts, "teardown_verified": True,
        "usage": {key: source[key] for key in (
            "new_tokens", "campaign_tokens", "all_attempt_tokens", "reported_charge_usd", "cost_basis",
        )},
        "evidence_path": "experiments/evidence/" + filename,
    }
