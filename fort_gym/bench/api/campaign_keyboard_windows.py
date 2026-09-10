"""Recorded saved windows with additive checkpoint, usage and loss lineage."""

from pathlib import Path
import re

from .campaign_keyboard_presave import _hash, _matches, _numbers, _read

COMPLETED_WINDOWS = (
    "astra_native_keyboard_completed_window_20260909x.json",
    "astra_native_keyboard_completed_window_20260909y.json",
    "astra_native_keyboard_completed_window_20260910ab.json",
)
COMPLETED_WINDOW_REVISIONS = {
    "astra_native_keyboard_completed_window_20260910ab.json":
        "18086313ee34a7df70efe1974f342df882976138",
}
PROGRESS = (
    "parent_checkpoint_cursor", "checkpoint_cursor", "parent_elapsed_ticks",
    "saved_elapsed_ticks", "new_saved_ticks", "new_model_responses",
    "cumulative_model_responses", "loss_records", "known_lost_ticks",
)
USAGE = ("new_tokens", "campaign_tokens", "all_attempt_tokens", "historical_failed_delivery_tokens")
OBSERVATION = (
    "population", "recorded_dead_citizens", "drink_stock", "completed_farms",
    "planned_unfinished_farms", "completed_beds", "completed_workshops",
)


def _counts(value: object, fields: tuple[str, ...]) -> dict:
    if not isinstance(value, dict):
        raise ValueError("Completed window counters must be an object")
    result = _numbers(value, fields)
    if any(number > 2**53 - 1 for number in result.values()):
        raise ValueError("Completed window counter exceeds exact display range")
    return result


def _observations(value: object, extra: tuple[str, ...] = ()) -> dict:
    fields = (*OBSERVATION, *extra)
    if not isinstance(value, dict) or any(key not in value for key in fields):
        raise ValueError("Completed window observations must be explicit")
    for key in fields:
        if value[key] is not None:
            _counts(value, (key,))
    return {key: value[key] for key in fields}


def _checkpoints(source: dict, progress: dict, usage: dict, parent: dict) -> list[dict]:
    rows = source.get("checkpoints")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 128:
        raise ValueError("Completed window must retain its ordered segment checkpoints")
    cursor = progress["parent_checkpoint_cursor"]
    elapsed = progress["parent_elapsed_ticks"]
    responses = parent["progress"]["cumulative_model_responses"]
    tokens = parent["usage"]["campaign_tokens"]
    previous_hash = source["parent_checkpoint_sha256"]
    seen = {previous_hash}
    result = []
    for index, row in enumerate(rows):
        counts = _counts(row, ("cursor", "saved_elapsed_ticks", "new_saved_ticks",
                               "new_model_responses", "cumulative_model_responses", "campaign_tokens"))
        for key in ("checkpoint_sha256", "checkpoint_file_sha256", "parent_checkpoint_sha256"):
            _hash(row.get(key), 64)
        _matches(row, {"parent_checkpoint_sha256": previous_hash,
                       "fresh_load_verified": index < len(rows) - 1})
        if (not 1 <= counts["new_model_responses"] <= 1024
                or counts["new_saved_ticks"] > counts["new_model_responses"] * source["max_advance_ticks"]
                or counts["cursor"] != cursor + counts["new_model_responses"]
                or counts["saved_elapsed_ticks"] != elapsed + counts["new_saved_ticks"]
                or counts["cumulative_model_responses"] != responses + counts["new_model_responses"]
                or counts["campaign_tokens"] <= tokens
                or row["checkpoint_sha256"] in seen):
            raise ValueError("Segment checkpoint lineage does not reconcile")
        cursor, elapsed = counts["cursor"], counts["saved_elapsed_ticks"]
        responses, tokens = counts["cumulative_model_responses"], counts["campaign_tokens"]
        previous_hash = row["checkpoint_sha256"]
        seen.add(previous_hash)
        result.append({**counts, **{key: row[key] for key in (
            "checkpoint_sha256", "checkpoint_file_sha256", "parent_checkpoint_sha256", "fresh_load_verified")}})
    if ((cursor, elapsed, responses, tokens, previous_hash) != (
            progress["checkpoint_cursor"], progress["saved_elapsed_ticks"],
            progress["cumulative_model_responses"], usage["campaign_tokens"], source["checkpoint_sha256"])
            or result[-1]["checkpoint_file_sha256"] != source["checkpoint_file_sha256"]):
        raise ValueError("Final segment checkpoint differs from the completed window")
    return result


def completed_window(root: Path, filename: str, parents: list[dict]) -> dict:
    return saved_window(root, filename, parents, paused=False)


def saved_window(root: Path, filename: str, parents: list[dict], *, paused: bool) -> dict:
    """Share save validation without reclassifying a paused window as completed."""
    source = _read(root, filename)
    schema = source.get("schema_version")
    schemas = (("fortgym.native-keyboard-paused-window/v1",) if paused else (
        "fortgym.native-keyboard-completed-window/v1", "fortgym.native-keyboard-completed-window/v2"))
    if not isinstance(schema, str) or schema not in schemas:
        raise ValueError("Unsupported saved window schema")
    status = "paused" if paused else "completed"
    candidates = [row for row in parents
                  if row.get("window_id", row.get("saved_segment_id")) == source.get("parent_record")]
    if len(candidates) != 1:
        raise ValueError("Completed window requires one published saved parent")
    parent = candidates[0]
    if filename.removesuffix(".json") == source["parent_record"]:
        raise ValueError("Completed window cannot be its own parent")
    _matches(source, {
        "schema_version": schema, "status": status,
        "parent_checkpoint_sha256": parent["checkpoint_sha256"],
        "control_profile": "native_keyboard/v2", "observation_profile": "native_screen_text/v1",
        "prompt_profile": "native_keyboard_memory_replacement/v1", "captured_screen_size": [120, 40],
        "snapshot_profile": "native_menu_preserving_save/v4", "runtime_rpc_transport": "native-rpc",
        **{key: True for key in (
            "checkpoint_verified", "parent_checkpoint_fresh_load_verified", "teardown_verified",
            "independent_audit_passed", "all_usage_retained", "saved_memory_retained",
        )},
        **{key: False for key in (
            "fresh_checkpoint_load_verified", "historical_failure_reclassified", "actions_replayed",
            "strategy_intervention", "reset_memory", "reset_usage", "sustainability_established",
            "matched_comparison", "loss_ticks_complete",
        )},
    })
    for field in ("model", "reasoning_effort"):
        if not isinstance(source.get(field), str) or not re.fullmatch(r"[a-z0-9][a-z0-9._/-]{0,99}", source[field]):
            raise ValueError("Completed window model declaration is invalid")
    _hash(source.get("source_revision"), 40)
    for field in ("checkpoint_sha256", "checkpoint_file_sha256", "independent_audit_sha256",
                  "condition_sha256", "window_sha256"):
        _hash(source.get(field), 64)
    p, usage = _counts(source.get("progress"), PROGRESS), _counts(source.get("usage"), USAGE)
    previous = parent["progress"]
    _matches(source.get("usage", {}), {"reported_charge_usd": None, "cost_basis": "codex_subscription_charge_unreported/v1"})
    if (
        not 1 <= p["new_model_responses"] <= 1024
        or p["parent_checkpoint_cursor"] != previous["checkpoint_cursor"]
        or p["checkpoint_cursor"] != p["parent_checkpoint_cursor"] + p["new_model_responses"]
        or p["parent_elapsed_ticks"] != previous["saved_elapsed_ticks"]
        or p["saved_elapsed_ticks"] != p["parent_elapsed_ticks"] + p["new_saved_ticks"]
        or p["cumulative_model_responses"] != previous["cumulative_model_responses"] + p["new_model_responses"]
        or any(p[key] != previous[key] for key in ("loss_records", "known_lost_ticks"))
        or source["checkpoint_sha256"] == parent["checkpoint_sha256"]
        or usage["new_tokens"] < 1
        or any(usage[key] != parent["usage"][key] + usage["new_tokens"] for key in ("campaign_tokens", "all_attempt_tokens"))
        or usage["historical_failed_delivery_tokens"] != parent["usage"]["historical_failed_delivery_tokens"]
        or usage["all_attempt_tokens"] != usage["campaign_tokens"] + usage["historical_failed_delivery_tokens"]
    ):
        raise ValueError("Completed window checkpoint, usage or losses do not reconcile")
    extra_furniture = ("completed_tables", "completed_chairs") if paused or schema.endswith("/v2") else ()
    observation = _observations(source.get("saved_observation"), extra_furniture)
    food = source.get("food", {})
    _matches(food, {"ownership_accessibility_assessed": False,
                    "production_consumption_measured": False})
    food_coverage = _counts(food, ("after_action_complete_readings", "after_action_unknown_readings"))
    inventory_fields = ("raw_edible_units", "trader_flagged_units", "in_job_units")
    if type(food.get("available")) is not bool or food.get("complete") is not food["available"]:
        raise ValueError("Completed window food availability must remain explicit")
    if food["available"]:
        inventory = _counts(food, inventory_fields)
        if any(inventory[key] > inventory["raw_edible_units"] for key in inventory_fields[1:]):
            raise ValueError("Completed window food flag counts exceed the inventory")
    else:
        _matches(food, {key: None for key in inventory_fields})
        inventory = {key: None for key in inventory_fields}
    timeout = source.get("private_measurement_timeout_seconds")
    if (not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 1 <= timeout <= 30
            or food_coverage["after_action_complete_readings"] + food_coverage["after_action_unknown_readings"] != p["new_model_responses"]):
        raise ValueError("Completed window food measurement is inconsistent")
    resources = _counts(source.get("resources"), (
        "memory_limit_bytes", "memory_peak_bytes", "memory_max_events", "oom_events",
        "oom_kill_events", "task_limit", "task_peak", "task_limit_events", "max_observed_zombies",
    ))
    _matches(source.get("resources", {}), {"headroom_established": False})
    if not resources["memory_limit_bytes"] or not resources["task_limit"]:
        raise ValueError("Completed window resource limits must be positive")
    clock = _counts(source.get("clock_outcomes"), ("zero_tick_timeouts", "advancing_decisions", "zero_tick_decisions"))
    max_ticks = source.get("max_advance_ticks")
    if type(max_ticks) is not int or not 1 <= max_ticks <= 2500:
        raise ValueError("Completed window must declare its native tick bound")
    if (clock["advancing_decisions"] + clock["zero_tick_decisions"] != p["new_model_responses"]
            or clock["zero_tick_timeouts"] > clock["zero_tick_decisions"]
            or p["new_saved_ticks"] > clock["advancing_decisions"] * max_ticks
            or (p["new_saved_ticks"] == 0) != (clock["advancing_decisions"] == 0)):
        raise ValueError("Completed window clock counts are inconsistent")
    return {
        "window_id": filename.removesuffix(".json"), "status": status,
        "parent_record": source["parent_record"], "source_revision": source["source_revision"],
        "model": source["model"], "reasoning_effort": source["reasoning_effort"],
        "checkpoint_sha256": source["checkpoint_sha256"], "progress": p,
        "checkpoint_verified": True, "parent_checkpoint_fresh_load_verified": True,
        "fresh_checkpoint_load_verified": False, "teardown_verified": True,
        "year_two_reached": p["saved_elapsed_ticks"] >= 403200,
        "sustainability_established": False, "matched_comparison": False, "loss_ticks_complete": False,
        "saved_observation": observation,
        "food": {**food_coverage, **inventory, "available": food["available"], "complete": food["complete"],
                 "ownership_accessibility_assessed": False, "production_consumption_measured": False},
        "private_measurement_timeout_seconds": timeout,
        "max_advance_ticks": max_ticks,
        "resources": {**resources, "headroom_established": False}, "clock_outcomes": clock,
        "usage": {**usage, "reported_charge_usd": None, "cost_basis": source["usage"]["cost_basis"]},
        "evidence_path": "experiments/evidence/" + filename,
        **({"evidence_revision": COMPLETED_WINDOW_REVISIONS[filename]}
           if filename in COMPLETED_WINDOW_REVISIONS else {}),
        **({"checkpoints": _checkpoints(source, p, usage, parent)}
           if paused or schema == "fortgym.native-keyboard-completed-window/v2" else {}),
    }
