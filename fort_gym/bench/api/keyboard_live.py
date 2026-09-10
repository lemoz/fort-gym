"""Allowlisted, expiring status from a host observer, separate from saved results."""

import json
from pathlib import Path
import re
import time

SCHEMA = "fortgym.public-keyboard-live/v1"
FRESH_SECONDS = 30
MAX_BYTES = 16384
COUNTS = (
    "saved_checkpoint_cursor",
    "saved_elapsed_ticks",
    "new_responses",
    "new_tokens",
    "campaign_responses",
    "campaign_tokens",
    "all_attempt_tokens",
    "window_response_limit",
    "deferrals_observed",
)


def saved_boundary(value: dict) -> dict:
    """Optional intermediate proof, not a terminal save-inventory acceptance."""
    if "latest_verified_save" not in value:
        if "ticks_since_verified_save_lower_bound" in value:
            raise ValueError("Post-save time requires a verified boundary")
        return {}
    saved = value["latest_verified_save"]
    counts = (
        "checkpoint_cursor",
        "elapsed_ticks",
        "window_responses",
        "campaign_tokens",
    )
    hashes = ("report_sha256", "checkpoint_sha256")
    if (
        not isinstance(saved, dict)
        or any(
            type(saved.get(k)) is not int or not 0 <= saved[k] <= 2**53 - 1
            for k in counts
        )
        or any(
            not isinstance(saved.get(k), str)
            or re.fullmatch(r"[a-f0-9]{64}", saved[k]) is None
            for k in hashes
        )
        or saved.get("evidence_basis") != "audited_save_metadata_and_next_worker_reload"
        or saved.get("full_inventory_and_trace_audit_complete") is not False
        or not 1 <= saved["window_responses"] < value["new_responses"]
        or saved["checkpoint_cursor"]
        != value["saved_checkpoint_cursor"] + saved["window_responses"]
        or saved["elapsed_ticks"] < value["saved_elapsed_ticks"]
        or not value["campaign_tokens"] - value["new_tokens"]
        <= saved["campaign_tokens"]
        <= value["campaign_tokens"]
    ):
        raise ValueError("Invalid intermediate saved boundary")
    ticks = value.get("ticks_since_verified_save_lower_bound", "missing")
    if ticks is not None and (
        type(ticks) is not int
        or ticks < 0
        or value["unsaved_ticks_lower_bound"] is None
        or ticks > value["unsaved_ticks_lower_bound"]
    ):
        raise ValueError("Invalid time after intermediate save")
    return {
        "latest_verified_save": {
            key: saved[key]
            for key in (
                *counts,
                *hashes,
                "evidence_basis",
                "full_inventory_and_trace_audit_complete",
            )
        },
        "ticks_since_verified_save_lower_bound": ticks,
    }


def project_status(value: dict, *, now: int) -> dict:
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA:
        raise ValueError("Unsupported live keyboard status")
    for key in ("run_id", "model", "reasoning_effort"):
        if (
            not isinstance(value.get(key), str)
            or re.fullmatch(r"[a-zA-Z0-9_.-]{1,100}", value[key]) is None
        ):
            raise ValueError("Invalid live run identity")
    if (
        not isinstance(value.get("source_revision"), str)
        or re.fullmatch(r"[a-f0-9]{40}", value["source_revision"]) is None
        or type(value.get("owner_alive")) is not bool
        or type(value.get("observed_at_unix")) is not int
        or value["observed_at_unix"] < 1
        or value["observed_at_unix"] > now + 5
        or value.get("reported_charge_usd", "missing") is not None
    ):
        raise ValueError("Invalid live observation boundary")
    for key in COUNTS:
        if type(value.get(key)) is not int or not 0 <= value[key] <= 2**53 - 1:
            raise ValueError("Invalid live count")
    unsaved = value.get("unsaved_ticks_lower_bound", "missing")
    if unsaved is not None and (
        type(unsaved) is not int or not 0 <= unsaved <= 2**53 - 1
    ):
        raise ValueError("Unknown elapsed time must remain unknown")
    if (
        not 1 <= value["window_response_limit"] <= 1024
        or value["new_responses"] > value["window_response_limit"]
        or value["campaign_responses"] < value["new_responses"]
        or value["campaign_tokens"] < value["new_tokens"]
        or value["all_attempt_tokens"] < value["campaign_tokens"]
        or value["deferrals_observed"] > value["new_responses"]
    ):
        raise ValueError("Live usage counters do not reconcile")
    age = max(0, now - value["observed_at_unix"])
    status = (
        "stale"
        if age > FRESH_SECONDS
        else ("running" if value["owner_alive"] else "stopped")
    )
    return {
        "schema_version": SCHEMA,
        "status": status,
        "fresh_for_seconds": FRESH_SECONDS,
        **{
            key: value[key]
            for key in (
                "run_id",
                "model",
                "reasoning_effort",
                "source_revision",
                "observed_at_unix",
                *COUNTS,
            )
        },
        "unsaved_ticks_lower_bound": unsaved,
        "reported_charge_usd": None,
        "progress_basis": "completed_host_receipts_and_subsequent_feedback",
        "new_save_verified": False,
        **saved_boundary(value),
    }


def live_status(root: Path | None, *, now: int | None = None) -> dict:
    if root is None:
        return {"schema_version": SCHEMA, "status": "not_connected"}
    path = root / "keyboard-active.json"
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("Live status must be a bounded regular file")
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES:
        raise ValueError("Live status exceeds its limit")
    return project_status(json.loads(raw), now=int(time.time()) if now is None else now)
