"""Provisional matched continuation observations bound to published saved inputs."""

import json
import time
from pathlib import Path

from .keyboard_cohort import STORAGE_BINDING, _read, keyboard_cohort
from .keyboard_cohort_live import MAX_BYTES, observation_fields

SCHEMA = "fortgym.public-matched-continuation-live/v1"
FILENAME = "keyboard-cohort-continuation-active.json"
DECLARATION_REVISION = "baee24bcef343d73922175439553306e95e3b01d"
INPUTS_PATH = "experiments/evidence/keyboard_matched_all_six_continuation_inputs_20260910.json"
INPUTS_SHA = "fb37d151a353c582265c21923e94fd5bbc3e59bd51c0f74fd65aa6ce55e4b98b"


def source_record(identity: str) -> tuple[dict, dict, dict, dict]:
    """Read only the fixed public cohort, readiness receipt and own declaration."""
    cohort = keyboard_cohort()
    found = [row for row in cohort["trials"] if row["campaign_id"] == identity]
    if len(found) != 1 or found[0]["result"] is None:
        raise ValueError("Unknown continuation source")
    row = found[0]
    readiness = _read(INPUTS_PATH, INPUTS_SHA)
    inputs = [r for r in readiness["inputs"] if r["campaign_id"] == identity]
    if len(inputs) != 1:
        raise ValueError("Missing own saved input")
    source = inputs[0]
    name = identity.removeprefix("matched-20260910-").replace("-", "_")
    window = _read(
        "experiments/keyboard_matched_continuations_20260910/" + name + "-32-64.json",
        source["declaration_sha256"],
    )
    result = row["result"]
    if (
        source["checkpoint_sha256"] != result["checkpoint_sha256"]
        or source["public_result_sha256"] != row["evidence_sha256"]
        or window["source_result_sha256"] != row["evidence_sha256"]
        or window["continuation_checkpoint_sha256"] != result["checkpoint_sha256"]
        or window["expected_campaign_id"] != identity
    ):
        raise ValueError("Continuation inputs differ from the recorded trial")
    return row, source, window, readiness


def identity_fields(identity: str) -> dict:
    row, source, _, _ = source_record(identity)
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
    observed = observation_fields(value, now=now)
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
