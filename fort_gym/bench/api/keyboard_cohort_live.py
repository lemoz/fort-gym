"""Expiring host-receipt observations, never claims of saved gameplay."""

import json
from pathlib import Path
import time

from .keyboard_cohort import (
    ORIGINAL_BINDING, PLAN_PATH, PLAN_REVISION, PLAN_SHA256, STORAGE_BINDING, _read,
)

SCHEMA = "fortgym.public-matched-live/v1"
FILENAME = "keyboard-cohort-active.json"
FRESH_SECONDS = 30
MAX_BYTES = 16384
COUNTS = ("responses", "returned_tokens", "unsettled_claims")
IDENTITY = ("campaign_id", "model", "reasoning_effort", "source_revision",
            "seed_receipt_sha256", "execution_binding_sha256", "data_disk_gib")


def project_status(value: dict, *, now: int) -> dict:
    """Project an allowlist; validate identities against the declared cohort."""
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA:
        raise ValueError("Unsupported matched live status")
    plan = _read(PLAN_PATH, PLAN_SHA256)
    found = [(i, r) for i, r in enumerate(plan["execution_order"])
             if r["campaign_id"] == value.get("campaign_id")]
    if len(found) != 1:
        raise ValueError("Unknown live trial")
    index, declared = found[0]
    if (value.get("model") != declared["model"]
            or value.get("reasoning_effort") != "medium"
            or value.get("source_revision") != PLAN_REVISION
            or value.get("seed_receipt_sha256") != plan["source_snapshot_receipt_sha256"]
            or value.get("execution_binding_sha256")
            != (ORIGINAL_BINDING if index < 2 else STORAGE_BINDING)
            or type(value.get("data_disk_gib")) is not int
            or value["data_disk_gib"] != (24 if index < 2 else 32)):
        raise ValueError("Live trial conditions do not match")
    if (type(value.get("controller_alive")) is not bool
            or type(value.get("observed_at_unix")) is not int
            or not 1 <= value["observed_at_unix"] <= now + 5
            or value.get("reported_charge_usd", "missing") is not None):
        raise ValueError("Invalid live observation boundary")
    for key in COUNTS:
        if type(value.get(key)) is not int or not 0 <= value[key] <= 2**53 - 1:
            raise ValueError("Invalid live count")
    if value["responses"] > 32 or value["responses"] + value["unsettled_claims"] > 32:
        raise ValueError("Live calls exceed the declared window")
    ticks = value.get("observed_elapsed_ticks_lower_bound", "missing")
    teardown = value.get("teardown_reported", "missing")
    if (ticks is not None and (type(ticks) is not int or not 0 <= ticks <= 2**53 - 1)
            or teardown is not None and type(teardown) is not bool
            or value["controller_alive"] and teardown is not None):
        raise ValueError("Unknown progress or teardown must remain unknown")
    age = max(0, now - value["observed_at_unix"])
    state = ("stale" if age > FRESH_SECONDS else
             "controller_running" if value["controller_alive"] else "controller_stopped")
    return {
        "schema_version": SCHEMA, "status": state,
        **{key: value[key] for key in (*IDENTITY, *COUNTS, "observed_at_unix")},
        "replicate": declared["replicate"], "cohort_id": plan["cohort_id"],
        "fresh_for_seconds": FRESH_SECONDS, "response_limit": 32,
        "observed_elapsed_ticks_lower_bound": ticks,
        "origin_kind": "independent_seed_trial", "new_save_verified": False,
        "progress_basis": "host_receipts_and_subsequent_feedback",
        "teardown_reported": teardown, "reported_charge_usd": None,
    }


def live_status(root: Path | None, *, now: int | None = None) -> dict:
    if root is None or not (root / FILENAME).exists() and not (root / FILENAME).is_symlink():
        return {"schema_version": SCHEMA, "status": "not_connected"}
    path = root / FILENAME
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("Live status must be a bounded regular file")
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES:
        raise ValueError("Live status exceeds its limit")
    return project_status(json.loads(raw), now=int(time.time()) if now is None else now)
