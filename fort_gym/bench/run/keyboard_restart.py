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
from .keyboard_partial_restart import (
    PARTIAL_FIELDS, PARTIAL_KIND, PARTIAL_STAGE, inspect_partial_failure, validate_partial_discontinuity,
)

from .keyboard_unavailable_restart import (
    UNAVAILABLE_KIND, UNAVAILABLE_STAGE, prepare_unavailable_restart, validate_unavailable_discontinuity,
)

SCHEMA = "fortgym.native-save-loss-restart/v1"
PRESAVE_STAGE = "identity_before_save"

def _failure_evidence(segment: Path, result: dict) -> dict:
    """Recognize the historical timeout or the retained pre-save Lua assertion."""
    if result.get("checkpoint_error") == "Native save completion was not observed before timeout":
        return {}
    if (
        result.get("checkpoint_error") != "Native menu identity probe returned malformed JSON"
        or result.get("private_save_attempt_retained") is not True
    ):
        raise ValueError("Restart requires a recognized native save failure")
    path = segment / "save-attempt.json"
    attempt = read(path)
    raw = attempt.get("identity_before_raw")
    if (
        set(attempt) != {
            "schema_version", "identity_before_raw", "screen_before", "screen_after",
            "world_before", "world_after",
        }
        or attempt.get("schema_version") != "fortgym.native-menu-save-attempt/v1"
        or not isinstance(raw, str)
        or re.match(
            r"^\(lua command\):[0-9]+: Identity probe requires a native screen\nstack traceback:\n",
            raw,
        ) is None
        or any(
            not isinstance(attempt.get(key), dict) or not attempt[key]
            for key in ("screen_before", "screen_after", "world_before", "world_after")
        )
        or attempt["screen_before"] != attempt["screen_after"]
        or attempt["world_before"] != attempt["world_after"]
        or attempt["world_after"] != read(segment / "native-after.json")
        or attempt["screen_after"] != read(segment / "final-screen.json")
    ):
        raise ValueError("Restart lacks unchanged, pre-save identity-probe evidence")
    return {
        "save_failure_stage": PRESAVE_STAGE,
        "source_save_attempt_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


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
        if "save_failure_stage" in row or "source_save_attempt_sha256" in row:
            if (
                row.get("save_failure_stage") not in {PRESAVE_STAGE, PARTIAL_STAGE, UNAVAILABLE_STAGE}
                or not isinstance(row.get("source_save_attempt_sha256"), str)
                or re.fullmatch("[a-f0-9]{64}", row["source_save_attempt_sha256"]) is None
            ):
                raise ValueError("Pre-save restart lacks digest-bound failure-stage evidence")
        if (row.get("failure_kind") == UNAVAILABLE_KIND
            or row.get("save_failure_stage") == UNAVAILABLE_STAGE
            or "lost_elapsed_ticks_complete" in row or "source_start_agent_sha256" in row):
            validate_unavailable_discontinuity(row)
        elif row.get("save_failure_stage") == PARTIAL_STAGE or PARTIAL_FIELDS.intersection(row):
            validate_partial_discontinuity(row)
        if (
            type(row.get("restored_next_step")) is not int
            or row["restored_next_step"] < 1
            or type(row.get("lost_trace_next_step")) is not int
            or row["lost_trace_next_step"] < row["restored_next_step"]
            or (row["lost_trace_next_step"] == row["restored_next_step"]
                and row.get("failure_kind") != UNAVAILABLE_KIND)
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

    declaration_fields = {
        "schema_version", "source_segment", "source_revision", "restored_next_step", "lost_trace_next_step",
    }
    partial = isinstance(declaration, dict) and declaration.get("failure_kind") == PARTIAL_KIND
    unavailable = isinstance(declaration, dict) and declaration.get("failure_kind") == UNAVAILABLE_KIND
    if (
        not isinstance(declaration, dict)
        or set(declaration) != declaration_fields | ({"failure_kind"} if partial or unavailable else set())
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
        or declaration["lost_trace_next_step"] < declaration["restored_next_step"]
        or (declaration["lost_trace_next_step"] == declaration["restored_next_step"] and not unavailable)
    ):
        raise ValueError("Invalid restart source identity or cursor")
    if source_root.is_symlink() or not source_root.is_dir():
        raise ValueError("Restart source must be a retained regular directory")
    if unavailable:
        return prepare_unavailable_restart(checkpoint, source_root, declaration, latest)
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
        or result.get("checkpoint_verified") is not False
        or result.get("recovery_requires_reconciliation") is not partial
        or result.get("stop_reason") != ("unsettled_failure" if partial else "segment_limit")
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
            != result["next_step"] - result["first_step"] + (1 if partial else 0)
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
    failure_evidence = (
        inspect_partial_failure(segment, checkpoint, result, returned, tail, latest)
        if partial else _failure_evidence(segment, result)
    )
    saved = payload["native_save"]
    native = source_root / f"runtime-{index}/runtime/data/save" / saved["save_name"]

    # DFHack appends its load log even when the actual game save is unchanged.
    def files(rows):
        return [row for row in rows if row["path"] != "events-dfhack.log"]

    if files(save_inventory(native)) != files(saved["files"]):
        raise ValueError("Newer native state exists; do not discard it as an unsaved tail")
    after = read(segment / "native-after.json")
    final = tail[-1]["tick_advance"]
    if _clock(after) != (final["end_year"] * 403200 + final["end_tick"]
                         + failure_evidence.get("lost_uncommitted_ticks", 0)):
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
        **failure_evidence,
    }
    return validate_discontinuities([record])[0]


def apply_restart(loop, record: dict, *, prior_discontinuities: list[dict] | None = None) -> None:
    """Attach factual loss feedback, not replacement gameplay or strategy."""
    if loop.agent.export_campaign_state()["usage"] != record["retained_usage"]:
        raise ValueError("Restart discarded prior model usage")
    history = loop.discontinuities if prior_discontinuities is None else validate_discontinuities(prior_discontinuities)
    if history[:len(loop.discontinuities)] != loop.discontinuities:
        raise ValueError("Restart cannot erase earlier checkpoint loss history")
    loop.discontinuities = validate_discontinuities([*history, record])
    loop.last_result = {
        "accepted": False,
        "why": "Infrastructure restart: the previous game save failed. The declared tail was not "
        "saved. The current screen and memory are from the restored checkpoint; all model "
        "usage remains counted. No previous key or action was replayed.",
        "restart": deepcopy(record),
        "previous_game_feedback": loop.last_result,
    }
    if record.get("lost_elapsed_ticks_complete") is False:
        loop.last_result["why"] += " The lost tick count is a confirmed lower bound; final uncommitted game time is unknown."
