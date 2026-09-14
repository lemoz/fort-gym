"""Provisional matched continuation observations bound to published saved inputs."""

import json
import time
from pathlib import Path

from .keyboard_cohort import STORAGE_BINDING, _read
from .keyboard_continuations import keyboard_continuations
from .keyboard_cohort_live import MAX_BYTES, observation_fields

SCHEMA = "fortgym.public-matched-endurance-live/v1"
FILENAME = "keyboard-cohort-endurance-active.json"
DECLARATION_REVISION = "45bb05c903181b6b2e4f61df3a4c0a8eca05b818"
INPUTS_PATH = "experiments/evidence/keyboard_matched_endurance_inputs_20260911.json"
INPUTS_SHA = "6e10884604fb56214f834d91ca20df41e067eab6f13e6ad1cbef89d984ea41b7"


def source_record(identity: str) -> tuple[dict, dict, dict, dict]:
    """Bind the next window to this attempt's audited decision-64 result."""
    cohort = keyboard_continuations()
    found = [row for row in cohort["trials"] if row["campaign_id"] == identity]
    if len(found) != 1 or found[0]["result"] is None:
        raise ValueError("Unknown endurance source")
    row = found[0]
    readiness = _read(INPUTS_PATH, INPUTS_SHA)
    inputs = [r for r in readiness["inputs"] if r["campaign_id"] == identity]
    if len(inputs) != 1 or len(readiness["inputs"]) != 6:
        raise ValueError("Missing own saved input")
    source = inputs[0]
    window = _read(source["declaration_path"], source["declaration_sha256"])
    result = row["result"]
    if (
        source["checkpoint_sha256"] != result["checkpoint_sha256"]
        or source["public_result_sha256"] != row["evidence_sha256"]
        or source["terminal_audit_sha256"] != result["audit_sha256"]
        or source["cursor"] != result["next_decision"]
        or source["cursor"] != 64
        or source["saved_elapsed_ticks"] != result["saved_elapsed_ticks"]
        or source["returned_tokens"] != result["usage"]["campaign_returned_tokens"]
        or window["source_result_sha256"] != row["evidence_sha256"]
        or window["continuation_checkpoint_sha256"] != result["checkpoint_sha256"]
        or window["expected_campaign_id"] != identity
        or window["continuation_from_next_step"] != 64
        or window["steps_per_segment"] != 64
        or window["max_segments"] != 1
        or window["window_end_decision"] != 128
    ):
        raise ValueError("Endurance inputs differ from the recorded trial")
    return row, source, window, readiness


def identity_fields(identity: str) -> dict:
    row, source, _, readiness = source_record(identity)
    result = row["result"]
    return {
        "campaign_id": identity,
        "model": row["model"],
        "reasoning_effort": "medium",
        "source_revision": result["execution"]["source_revision"],
        "seed_receipt_sha256": result["execution"]["seed_receipt_sha256"],
        "execution_binding_sha256": STORAGE_BINDING,
        "data_disk_gib": 32,
        "prior_checkpoint_sha256": source["checkpoint_sha256"],
        "window_sha256": source["declaration_sha256"],
        "declaration_revision": DECLARATION_REVISION,
        "controller_source_sha256": readiness["controller_source_sha256"],
        "host_courier_sha256": readiness["host_courier_sha256"],
    }


def project_status(value: dict, *, now: int) -> dict:
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA:
        raise ValueError("Unsupported continuation observation")
    identity = value.get("campaign_id")
    if not isinstance(identity, str):
        raise ValueError("Continuation campaign identity must be text")
    expected = identity_fields(identity)
    if any(type(value.get(k)) is not type(v) or value[k] != v for k, v in expected.items()):
        raise ValueError("Continuation identity or saved source differs")
    row, source, window, _ = source_record(identity)
    observed = observation_fields(value, now=now, response_limit=window["steps_per_segment"])
    new_ticks = observed.pop("observed_elapsed_ticks_lower_bound")
    saved_ticks = source["saved_elapsed_ticks"]
    if (
        observed["returned_tokens"] > 2**53 - 1 - source["returned_tokens"]
        or new_ticks is not None
        and new_ticks > 2**53 - 1 - saved_ticks
    ):
        raise ValueError("Cumulative observation exceeds exact numeric representation")
    return {
        "schema_version": SCHEMA,
        **expected,
        **observed,
        "replicate": row["replicate"],
        "cohort_id": row["result"]["cohort_id"],
        "origin_kind": "saved_campaign_checkpoint",
        "start_decision": source["cursor"],
        "end_decision": source["cursor"] + window["steps_per_segment"],
        "source_checkpoint_verified": True,
        "saved_elapsed_ticks_before_window": saved_ticks,
        "returned_tokens_before_window": source["returned_tokens"],
        "new_elapsed_ticks_lower_bound": new_ticks,
        "campaign_elapsed_ticks_lower_bound": saved_ticks + (new_ticks or 0),
        "campaign_returned_responses": source["cursor"] + observed["responses"],
        "campaign_returned_tokens": source["returned_tokens"] + observed["returned_tokens"],
        "source_result_url": row["evidence_url"],
    }


def live_status(root: Path | None, *, now: int | None = None) -> dict:
    if root is None or not (root / FILENAME).exists() and not (root / FILENAME).is_symlink():
        return {"schema_version": SCHEMA, "status": "not_connected"}
    path = root / FILENAME
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("Continuation observation must be a bounded regular file")
    data = path.read_bytes()
    if len(data) > MAX_BYTES:
        raise ValueError("Continuation observation exceeds its limit")
    return project_status(json.loads(data), now=int(time.time()) if now is None else now)
