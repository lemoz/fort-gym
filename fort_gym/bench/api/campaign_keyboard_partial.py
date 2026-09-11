"""Recorded partial-action failures, separate from saved progress and restart."""

from pathlib import Path

from .campaign_keyboard_presave import _hash, _matches, _numbers, _read

PARTIAL_FAILURES = ("astra_native_keyboard_partial_failure_20260908.json",)
PROGRESS = (
    "checkpointed_elapsed_ticks",
    "committed_trace_next_step",
    "committed_trace_elapsed_ticks",
    "new_committed_decisions",
    "new_model_responses",
    "new_committed_ticks",
    "uncommitted_responses",
    "uncommitted_native_ticks",
    "unsaved_new_native_ticks",
    "accounted_model_responses",
    "inherited_save_loss_restarts",
    "inherited_discarded_native_ticks",
)
USAGE = ("new_tokens", "campaign_tokens", "all_attempt_tokens", "historical_failed_delivery_tokens")
SOURCE_DIGESTS = ("segment_result", "trace", "usage", "partial_failure", "save_attempt", "runtime")
FAILURE = {
    "clock_reason": "interrupt_baseline_mismatch",
    "save_stage": "identity_after_save_request_pending",
    "native_save_requested": True,
    "save_remained_pending": True,
    "clean_interruption_with_post_input_boundary": True,
}


def partial_failure(root: Path, filename: str, parents: list[dict]) -> dict:
    """Project only audited counters; never expose raw model/game evidence."""
    source = _read(root, filename)
    parent = next(
        (row for row in parents if row["continuation_id"] == source["parent_record"]), None
    )
    if parent is None or parent.get("snapshot_profile") != "native_menu_preserving_save/v4":
        raise ValueError("Partial failure requires its published v4 continuation parent")
    _matches(
        source,
        {
            "schema_version": "fortgym.native-keyboard-partial-failure-summary/v1",
            "status": "failed",
            "model": "gpt-6-astra",
            "reasoning_effort": "medium",
            "control_profile": "native_keyboard/v2",
            "observation_profile": "native_screen_text/v1",
            "snapshot_profile": "native_menu_preserving_save/v4",
            "captured_screen_size": [120, 40],
            "independent_failure_audit_passed": True,
            "teardown_verified": True,
            "native_load_verified": True,
            "original_failure_preserved": True,
            "last_checkpoint_save_files_unchanged_except_event_log": True,
            "new_checkpoint_created": False,
            "new_restart_performed": False,
            "gameplay_rescue_or_replay_performed": False,
            "last_verified_checkpoint_cursor": parent["checkpoint_cursor"],
            "last_verified_checkpoint_sha256": parent["checkpoint_sha256"],
        },
    )
    _matches(source["failure"], FAILURE)
    _hash(source["source_revision"], 40)
    _hash(source["private_failure_audit_sha256"], 64)
    digests = source["source_evidence_sha256"]
    if not isinstance(digests, dict):
        raise ValueError("Partial failure requires digest-bound evidence")
    for key in SOURCE_DIGESTS:
        _hash(digests.get(key), 64)
    progress = _numbers(source["progress"], PROGRESS)
    usage = _numbers(source["usage"], USAGE)
    _matches(
        source["usage"],
        {
            "reported_charge_usd": None,
            "cost_basis": "codex_subscription_charge_unreported/v1",
        },
    )
    if (
        progress["new_committed_decisions"] < 1
        or progress["uncommitted_responses"] != 1
        or not 0 < progress["uncommitted_native_ticks"] <= 2550
        or progress["new_model_responses"] != progress["new_committed_decisions"] + 1
        or progress["committed_trace_next_step"]
        != parent["checkpoint_cursor"] + progress["new_committed_decisions"]
        or progress["checkpointed_elapsed_ticks"] != parent["progress"]["retained_elapsed_ticks"]
        or progress["committed_trace_elapsed_ticks"]
        != progress["checkpointed_elapsed_ticks"] + progress["new_committed_ticks"]
        or progress["unsaved_new_native_ticks"]
        != progress["new_committed_ticks"] + progress["uncommitted_native_ticks"]
        or progress["accounted_model_responses"]
        != parent["progress"]["cumulative_model_responses"] + progress["new_model_responses"]
        or progress["inherited_save_loss_restarts"]
        != parent["progress"]["native_save_loss_restarts"]
        or progress["inherited_discarded_native_ticks"]
        != parent["progress"]["discarded_native_ticks"]
        or usage["new_tokens"] < 1
        or any(
            usage[key] != parent["usage"][key] + usage["new_tokens"]
            for key in ("campaign_tokens", "all_attempt_tokens")
        )
        or usage["all_attempt_tokens"]
        != usage["campaign_tokens"] + usage["historical_failed_delivery_tokens"]
    ):
        raise ValueError("Partial failure usage or unsaved progress does not reconcile")
    return {
        "failure_id": filename.removesuffix(".json"),
        "status": "failed",
        "parent_record": source["parent_record"],
        "source_revision": source["source_revision"],
        "checkpoint_cursor": parent["checkpoint_cursor"],
        "checkpoint_sha256": parent["checkpoint_sha256"],
        "progress": progress,
        "failure": dict(FAILURE),
        "usage": {
            **usage,
            "reported_charge_usd": None,
            "cost_basis": "codex_subscription_charge_unreported/v1",
        },
        "new_checkpoint_created": False,
        "new_restart_performed": False,
        "native_load_verified": True,
        "teardown_verified": True,
        "evidence_path": "experiments/evidence/" + filename,
    }
