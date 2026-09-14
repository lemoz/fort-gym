"""Public OOM-flagged runs: unknown tails and observer effects stay visible."""

from pathlib import Path

from .campaign_keyboard_presave import _hash, _matches, _numbers, _read

OOM_FAILURES = ("astra_native_keyboard_oom_failure_20260908.json",)
PROGRESS = (
    "checkpointed_elapsed_ticks",
    "committed_trace_cursor",
    "new_committed_decisions",
    "new_model_responses",
    "new_committed_unsaved_ticks",
    "uncommitted_model_responses",
    "uncommitted_native_keys_confirmed",
    "accounted_responses",
    "existing_loss_records",
    "existing_lost_ticks",
    "latest_attested_paused_year",
    "latest_attested_paused_tick",
    "last_population",
    "last_recorded_dead",
)
USAGE = ("new_tokens", "campaign_tokens", "all_attempt_tokens", "historical_failed_delivery_tokens")
DIGESTS = (
    "independent_failure_audit_sha256",
    "independent_failure_audit_script_sha256",
    "owner_result_sha256",
    "runtime_result_sha256",
    "container_state_sha256",
)
SOURCE_DIGESTS = (
    "result.json",
    "save-attempt.json",
    "agent-after.json",
    "loop/trace.jsonl",
    "loop/usage.jsonl",
    "loop/failures.jsonl",
    "restart.json",
)


def oom_failure(root: Path, filename: str, parents: list[dict]) -> dict:
    """Expose only selected, reconciled publication fields, never raw traces."""
    source = _read(root, filename)
    parent = next(
        (row for row in parents if row["failure_id"] + ".json" == source.get("parent_record")), None
    )
    if parent is None:
        raise ValueError("OOM publication requires its recorded partial-failure parent")
    _matches(
        source,
        {
            "schema_version": "fortgym.native-keyboard-oom-failure-summary/v1",
            "classification": "infrastructure_failure_oom_flagged",
            "model": "gpt-6-astra",
            "reasoning_effort": "medium",
            "control_profile": "native_keyboard/v2",
            "observation_profile": "native_screen_text/v1",
            "snapshot_profile": "native_menu_preserving_save/v4",
            "screen_size": [120, 40],
            "oom_victim": "not_established",
            "exact_oom_cause": "not_established",
            "independent_failure_audit_passed": True,
            "native_load_verified": True,
            "teardown_verified": True,
            "every_subscription_event_receipt_redecoded": True,
            "native_save_world_sav_matches_parent": True,
            "save_inventory_changed_paths": ["events-dfhack.log"],
            "new_checkpoint_verified": False,
            "another_restart_performed": False,
            "gameplay_collapse_proven": False,
            "clock_fix_native_acceptance": False,
            "uncommitted_clock_receipt_available": False,
            "final_calendar_observation_available": False,
            "uncommitted_elapsed_ticks": None,
            "reported_charge_usd": None,
            "last_checkpoint_cursor": parent["checkpoint_cursor"],
            "last_checkpoint_sha256": parent["checkpoint_sha256"],
            "live_tracking": False,
        },
    )
    _hash(source["source_revision"], 40)
    for key in DIGESTS:
        _hash(source.get(key), 64)
    digests = source.get("source_sha256")
    if not isinstance(digests, dict):
        raise ValueError("OOM publication lacks native evidence digests")
    for key in SOURCE_DIGESTS:
        _hash(digests.get(key), 64)
    progress, usage = _numbers(source, PROGRESS), _numbers(source, USAGE)
    previous = parent["progress"]
    if (
        progress["new_committed_decisions"] < 1
        or progress["new_committed_decisions"] > 64
        or progress["uncommitted_model_responses"] != 1
        or not 0 < progress["uncommitted_native_keys_confirmed"] <= 64
        or progress["new_model_responses"] != progress["new_committed_decisions"] + 1
        or progress["committed_trace_cursor"]
        != parent["checkpoint_cursor"] + progress["new_committed_decisions"]
        or progress["checkpointed_elapsed_ticks"] != previous["checkpointed_elapsed_ticks"]
        or progress["accounted_responses"]
        != previous["accounted_model_responses"] + progress["new_model_responses"]
        or progress["existing_loss_records"] != previous["inherited_save_loss_restarts"] + 1
        or progress["existing_lost_ticks"]
        != previous["inherited_discarded_native_ticks"] + previous["unsaved_new_native_ticks"]
        or progress["new_committed_unsaved_ticks"] > 2000 * progress["new_committed_decisions"]
        or progress["latest_attested_paused_tick"] >= 403200
        or usage["new_tokens"] < 1
        or any(
            usage[key] != parent["usage"][key] + usage["new_tokens"]
            for key in ("campaign_tokens", "all_attempt_tokens")
        )
        or usage["historical_failed_delivery_tokens"]
        != parent["usage"]["historical_failed_delivery_tokens"]
        or usage["all_attempt_tokens"]
        != usage["campaign_tokens"] + usage["historical_failed_delivery_tokens"]
    ):
        raise ValueError("OOM publication progress, prior losses or usage do not reconcile")
    return {
        "failure_id": filename.removesuffix(".json"),
        "parent_record": parent["failure_id"],
        "source_revision": source["source_revision"],
        "status": "infrastructure_failure_oom_flagged",
        "checkpoint_cursor": parent["checkpoint_cursor"],
        "checkpoint_sha256": parent["checkpoint_sha256"],
        "progress": {**progress, "uncommitted_elapsed_ticks": None},
        "usage": {
            **usage,
            "reported_charge_usd": None,
            "cost_basis": "codex_subscription_charge_unreported/v1",
        },
        "oom_victim": "not_established",
        "exact_oom_cause": "not_established",
        "possible_observer_contribution": True,
        "final_calendar_observation_available": False,
        "new_checkpoint_created": False,
        "another_restart_performed": False,
        "native_load_verified": True,
        "teardown_verified": True,
        "evidence_path": "experiments/evidence/" + filename,
    }
