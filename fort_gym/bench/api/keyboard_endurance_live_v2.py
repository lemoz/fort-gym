"""Longer-window observations bound to recorded own-save campaign history."""

import json
import time
from pathlib import Path

from ..run.matched_endurance import next_window
from ..run.matched_result_chain import digest
from .keyboard_cohort import PLAN_PATH, PLAN_SHA256, _link, _read
from .keyboard_cohort_live import MAX_BYTES, observation_fields
from .keyboard_endurance_live import source_record as original_source
from .keyboard_endurance_records import keyboard_endurance_records

SCHEMA = "fortgym.public-matched-endurance-live/v2"
FILENAME = "keyboard-cohort-endurance-v2-active.json"
DECLARATION_REVISION = "4590fc1828365c44c9a4d3be728b4168ded5c514"
CONTROLLER_SHA = "063b4c600d47590aa8fc9b5a690362f719c2ba61a3238439cf9760184adb8011"
COURIER_SHA = "1d0ef1648a6222acbe6a1501dfa950a8433afcda8771e770315354e6f717acd1"


def source_record(identity: str) -> tuple[dict, dict, dict]:
    """Find the exact decision-128 parent, even after later results are added."""
    trials = keyboard_endurance_records()["trials"]
    found = [row for row in trials if row["campaign_id"] == identity]
    if len(found) != 1:
        raise ValueError("Unknown longer-window campaign")
    row = found[0]
    parents = [
        entry
        for entry in row["windows"]
        if entry["result"]["next_decision"] == 128
        and entry["result"]["status"] == "completed"
    ]
    if len(parents) != 1:
        raise ValueError("Missing audited decision-128 parent")
    parent = parents[0]
    _, _, template, _ = original_source(identity)
    plan = _read(PLAN_PATH, PLAN_SHA256)
    declared = next(
        value for value in plan["execution_order"] if value["campaign_id"] == identity
    )
    condition = _read(
        "experiments/keyboard_matched_pilot_20260910/" + declared["condition"],
        parent["result"]["execution"]["condition_file_sha256"],
    )
    window = next_window(
        parent["result"],
        parent["evidence_sha256"],
        [*template["source_result_chain_sha256"], parent["evidence_sha256"]],
        template,
        plan=plan,
        row=declared,
        condition=condition,
    )
    if (
        window["continuation_from_next_step"],
        window["window_end_decision"],
        window["steps_per_segment"],
        window["max_segments"],
    ) != (128, 256, 64, 2):
        raise ValueError("Longer window differs from the declared stage")
    return row, parent, window


def _identity(row: dict, parent: dict, window: dict) -> dict:
    saved = parent["result"]
    return {
        "schema_version": SCHEMA,
        "campaign_id": row["campaign_id"],
        "model": row["model"],
        "reasoning_effort": "medium",
        "replicate": row["replicate"],
        "source_revision": saved["execution"]["source_revision"],
        "controller_source_sha256": CONTROLLER_SHA,
        "host_courier_sha256": COURIER_SHA,
        "declaration_revision": DECLARATION_REVISION,
        "window_sha256": digest(window),
        "prior_checkpoint_sha256": saved["checkpoint_sha256"],
        "start_decision": 128,
        "end_decision": 256,
        "data_disk_gib": 32,
        "origin_kind": "saved_campaign_checkpoint",
        "cohort_id": saved["cohort_id"],
        "saved_elapsed_ticks_before_window": saved["saved_elapsed_ticks"],
        "returned_tokens_before_window": saved["usage"]["campaign_returned_tokens"],
    }


def identity_fields(identity: str) -> dict:
    return _identity(*source_record(identity))


def project_status(value: dict, *, now: int) -> dict:
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA:
        raise ValueError("Unsupported longer-window observation")
    identity = value.get("campaign_id")
    if not isinstance(identity, str):
        raise ValueError("Campaign identity must be text")
    row, parent, window = source_record(identity)
    expected = _identity(row, parent, window)
    if any(
        type(value.get(key)) is not type(wanted) or value[key] != wanted
        for key, wanted in expected.items()
    ):
        raise ValueError("Longer-window identity or saved source differs")
    limit = window["steps_per_segment"] * window["max_segments"]
    observed = observation_fields(value, now=now, response_limit=limit)
    ticks = observed.pop("observed_elapsed_ticks_lower_bound")
    total_ticks = expected["saved_elapsed_ticks_before_window"] + (ticks or 0)
    total_tokens = (
        expected["returned_tokens_before_window"] + observed["returned_tokens"]
    )
    if max(total_ticks, total_tokens) > 2**53 - 1:
        raise ValueError("Cumulative observation exceeds exact representation")
    audited = [
        entry
        for entry in row["windows"]
        if entry["result"]["start_decision"] == expected["start_decision"]
        and entry["result"]["execution"]["window_sha256"] == expected["window_sha256"]
    ]
    short = identity.removeprefix("matched-20260910-").replace("-", "_")
    return {
        **expected,
        **observed,
        "source_checkpoint_verified": True,
        "new_elapsed_ticks_lower_bound": ticks,
        "campaign_elapsed_ticks_lower_bound": total_ticks,
        "campaign_returned_responses": expected["start_decision"]
        + observed["responses"],
        "campaign_returned_tokens": total_tokens,
        "source_result_url": parent["evidence_url"],
        "declaration_url": _link(
            "experiments/keyboard_matched_endurance_20260911/"
            + short
            + "-128-256.json",
            DECLARATION_REVISION,
        ),
        "audited_result_url": audited[-1]["evidence_url"] if audited else None,
    }


def live_status(root: Path | None, *, now: int | None = None) -> dict:
    if (
        root is None
        or not (root / FILENAME).exists()
        and not (root / FILENAME).is_symlink()
    ):
        return {"schema_version": SCHEMA, "status": "not_connected"}
    path = root / FILENAME
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("Longer-window observation must be a bounded regular file")
    data = path.read_bytes()
    if len(data) > MAX_BYTES:
        raise ValueError("Longer-window observation exceeds its limit")
    return project_status(
        json.loads(data), now=int(time.time()) if now is None else now
    )
