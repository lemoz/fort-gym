"""Explicit loss-aware restart after an audited, fully accounted save failure.

This is not forward recovery: native progress is lost. Original traces and
usage remain untouched, and the discontinuity follows subsequent checkpoints.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path

from ..agent.campaign_keyboard import validate_usage
from ..agent.keyboard_exchange import read
from .campaign_checkpoint import verify_checkpoint
from .campaign_save import save_inventory

SCHEMA = "fortgym.native-save-loss-restart/v1"


def validate_discontinuities(records: object) -> list[dict]:
    if not isinstance(records, list) or len(records) > 64:
        raise ValueError("Invalid campaign discontinuity list")
    identities = set()
    for row in records:
        if not isinstance(row, dict) or row.get("schema_version") != SCHEMA:
            raise ValueError("Invalid native save-loss restart")
        for key in (
            "checkpoint_sha256",
            "source_result_sha256",
            "source_trace_sha256",
            "source_usage_sha256",
        ):
            if not isinstance(row.get(key), str) or re.fullmatch("[a-f0-9]{64}", row[key]) is None:
                raise ValueError("Restart lacks digest-bound source evidence")
        if row["source_result_sha256"] in identities:
            raise ValueError("Duplicate native save-loss restart")
        identities.add(row["source_result_sha256"])
        if (
            type(row.get("restored_next_step")) is not int
            or row["restored_next_step"] < 1
            or type(row.get("lost_trace_next_step")) is not int
            or row["lost_trace_next_step"] <= row["restored_next_step"]
            or type(row.get("lost_elapsed_ticks")) is not int
            or row["lost_elapsed_ticks"] < 0
            or row.get("memory_policy") != "restore_checkpoint_memory"
            or row.get("uninterrupted_campaign") is not False
            or row.get("actions_replayed") is not False
        ):
            raise ValueError("Restart must explicitly retain native progress loss")
        usage = row.get("retained_usage")
        if not isinstance(usage, dict):
            raise ValueError("Restart must retain model usage")
        validate_usage(usage)
    return deepcopy(records)


def prepare_restart(checkpoint: Path, source_root: Path, declaration: dict, latest: bytes) -> dict:
    """Verify the failed segment, fully counted journal, and unchanged native save."""
    from .campaign_loop import _clock, reconciled_usage

    if (
        not isinstance(declaration, dict)
        or set(declaration)
        != {
            "schema_version",
            "source_segment",
            "source_revision",
            "restored_next_step",
            "lost_trace_next_step",
        }
        or declaration["schema_version"] != SCHEMA
    ):
        raise ValueError("Restart requires an explicit source declaration")
    index = declaration["source_segment"]
    if type(index) is not int or not 0 <= index < 16:
        raise ValueError("Invalid restart source segment")
    if (
        not isinstance(declaration["source_revision"], str)
        or re.fullmatch("[a-f0-9]{40}", declaration["source_revision"]) is None
        or any(
            type(declaration[key]) is not int or declaration[key] < 1
            for key in ("restored_next_step", "lost_trace_next_step")
        )
        or declaration["lost_trace_next_step"] <= declaration["restored_next_step"]
    ):
        raise ValueError("Invalid restart source identity or cursor")
    if source_root.is_symlink() or not source_root.is_dir():
        raise ValueError("Restart source must be a retained regular directory")
    segment = source_root / f"segment-{index}"
    manifest = verify_checkpoint(checkpoint)
    payload, state = manifest["payload"], read(checkpoint / "agent.json")
    result, returned = read(segment / "result.json"), read(segment / "agent-after.json")
    trace_path, usage_path = segment / "loop/trace.jsonl", segment / "loop/usage.jsonl"
    trace = trace_path.read_bytes()
    old_trace, old_usage = (
        (checkpoint / "trace.jsonl").read_bytes(),
        (checkpoint / "usage.jsonl").read_bytes(),
    )
    if (
        result.get("schema_version") != "fortgym.keyboard-segment/v1"
        or result.get("status") != "checkpoint_failed"
        or result.get("checkpoint_error_type") != "CampaignSaveError"
        or result.get("checkpoint_error")
        != "Native save completion was not observed before timeout"
        or result.get("checkpoint_verified") is not False
        or result.get("recovery_requires_reconciliation") is not False
        or result.get("stop_reason") != "segment_limit"
        or result.get("campaign_id") != payload["campaign_id"]
        or result.get("source_revision") != declaration["source_revision"]
        or result.get("first_step") != payload["next_step"]
        or result.get("first_step") != declaration["restored_next_step"]
        or result.get("next_step") != declaration["lost_trace_next_step"]
        or (segment / "checkpoint/checkpoint.json").exists()
        or not trace.startswith(old_trace)
        or not trace.endswith(b"\n")
        or not latest.startswith(old_usage)
        or latest != usage_path.read_bytes()
        or returned.get("configuration") != state["configuration"]
        or returned.get("campaign_id") != state["campaign_id"]
        or returned.get("usage") != result.get("usage")
        or reconciled_usage(state, latest) != returned["usage"]
        or any(
            returned["usage"][key] - state["usage"][key]
            != result["next_step"] - result["first_step"]
            for key in ("returned_responses", "accounted_responses", "dispatched_requests")
        )
    ):
        raise ValueError("Restart source is not a settled, fully retained native save failure")
    tail = [json.loads(line) for line in trace[len(old_trace) :].splitlines()]
    if (
        not tail
        or [row.get("step") for row in tail]
        != list(range(result["first_step"], result["next_step"]))
        or any(
            row.get("run_id") != payload["campaign_id"]
            or row.get("execute", {}).get("accepted") is not True
            for row in tail
        )
    ):
        raise ValueError("Lost trace must contain exactly the declared accepted tail")
    saved = payload["native_save"]
    native = source_root / f"runtime-{index}/runtime/data/save" / saved["save_name"]

    # DFHack appends its load log even when the actual game save is unchanged.
    def files(rows):
        return [row for row in rows if row["path"] != "events-dfhack.log"]

    if files(save_inventory(native)) != files(saved["files"]):
        raise ValueError("Newer native state exists; do not discard it as an unsaved tail")
    after = read(segment / "native-after.json")
    final = tail[-1]["tick_advance"]
    if _clock(after) != final["end_year"] * 403200 + final["end_tick"]:
        raise ValueError("Failed segment native boundary differs from its trace")
    lost = _clock(after) - (saved["year"] * 403200 + saved["year_tick"])

    def digest(data):
        return hashlib.sha256(data).hexdigest()

    record = {
        "schema_version": SCHEMA,
        "checkpoint_sha256": manifest["sha256"],
        "source_result_sha256": digest((segment / "result.json").read_bytes()),
        "source_trace_sha256": digest(trace),
        "source_usage_sha256": digest(latest),
        "restored_next_step": result["first_step"],
        "lost_trace_next_step": result["next_step"],
        "lost_elapsed_ticks": lost,
        "retained_usage": returned["usage"],
        "memory_policy": "restore_checkpoint_memory",
        "uninterrupted_campaign": False,
        "actions_replayed": False,
    }
    return validate_discontinuities([record])[0]


def apply_restart(loop, record: dict) -> None:
    """Attach factual loss feedback, not replacement gameplay or strategy."""
    if loop.agent.export_campaign_state()["usage"] != record["retained_usage"]:
        raise ValueError("Restart discarded prior model usage")
    loop.discontinuities = validate_discontinuities([*loop.discontinuities, record])
    loop.last_result = {
        "accepted": False,
        "why": "Infrastructure restart: the previous game save failed. The declared tail was not "
        "saved. The current screen and memory are from the restored checkpoint; all model "
        "usage remains counted. No previous key or action was replayed.",
        "restart": deepcopy(record),
        "previous_game_feedback": loop.last_result,
    }
