"""Export audited public-owner windows through the existing spectator format."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from fort_gym.bench.agent.keyboard_exchange import digest, read, validate_request
from fort_gym.bench.api import watch
from fort_gym.bench.run.campaign_checkpoint import verify_checkpoint
from fort_gym.bench.run.keyboard_config import validate_condition
from fort_gym.bench.run.keyboard_docker_audit_contract import (
    SCHEMA as RUN_AUDIT_SCHEMA,
    verify_artifact_hashes,
)
from scripts.export_displayed_key_recording import recorded_action


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require(value: bool, message: str) -> None:
    if not value:
        raise ValueError(message)


def receipts(attempt: Path) -> list[tuple[dict, dict, dict]]:
    """Read only complete, bound host responses; never expose private memory."""
    records = []
    for path in (attempt / "model").glob("*/summary.json"):
        summary = read(path)
        request, response = read(path.parent / "request.json"), read(path.parent / "response.json")
        validate_request(request)
        claim = read(path.parent / "claim.json")
        require(
            request["request_id"] == summary["request_id"] == path.parent.name
            and response["request_sha256"] == claim["request_sha256"] == digest(request),
            "Request, claim and response binding differs",
        )
        records.append((summary, request, response["result"]))
    records.sort(key=lambda row: row[0]["decision_index"])
    require(len(records) <= 1024 and [row[0]["decision_index"] for row in records] ==
            list(range(len(records))), "Receipt coverage is not consecutive")
    return records


def export_window(attempt: Path, audit: dict, proof: dict) -> tuple[list[dict], dict, dict]:
    """Project only a checkpoint's own audited window, preserving decision offsets."""
    require(sha(attempt / "owner-result.json") == proof["owner_result_sha256"] and
            sha(attempt / "game/native/result.json") == proof["native_result_sha256"],
            "Owner or native result differs from audit")
    owner, native = read(attempt / "owner-result.json"), read(attempt / "game/native/result.json")
    plan = read(attempt / "owner-plan.json")
    require(owner["status"] == "execution_finished" and owner["native_result"] == native
            and owner["original_inputs_unchanged"] is True
            and owner["container_stopped_verified"] is True
            and native["runtime_cleanup_verified"] is True
            and owner["campaign_id"] == native["campaign_id"] == audit["campaign_id"]
            and owner["source_revision"] == native["source_revision"] == audit["source_revision"]
            and owner["image"] == audit["image"]
            and owner["mode"] == plan["mode"] == proof["mode"], "Unsettled or different owner window")
    condition = read(attempt / "game/native/condition.json")
    validate_condition(condition)
    require(digest(condition) == plan["condition_sha256"], "Native condition changed")
    segments = [native["segment"]] if owner["mode"] == "fresh" else native["segments"]
    require(bool(segments) and len(segments) <= 16, "Missing native segment")
    checkpoint = attempt / f"game/native/segment-{len(segments) - 1}/checkpoint"
    manifest = verify_checkpoint(checkpoint)
    require(sha(checkpoint / "checkpoint.json") == proof["checkpoint_file_sha256"]
            and manifest["sha256"] == proof["checkpoint_manifest_sha256"]
            and manifest["payload"]["next_step"] == proof["next_step"]
            and manifest["payload"]["campaign_id"] == audit["campaign_id"]
            and manifest["payload"]["code_revision"] == audit["source_revision"],
            "Checkpoint differs from audited source")
    state = read(checkpoint / "agent.json")
    require(state["usage"]["total_tokens"] == proof["cumulative_returned_tokens"],
            "Saved usage differs from audit")
    end, count = proof["next_step"], proof["new_model_responses"]
    require(type(end) is int and type(count) is int and 1 <= count <= min(end, 1024),
            "Invalid window boundary")
    first = end - count
    rows = [json.loads(line) for line in (checkpoint / "trace.jsonl").read_bytes().splitlines()]
    require([row["step"] for row in rows] == list(range(end)), "Saved trace boundary differs")
    entries = receipts(attempt)
    require(len(entries) == count and
            [row[0] for row in entries] == owner["model_responses"], "Response count differs")
    frames, tokens = [], 0
    for (summary, request, result), row in zip(entries, rows[first:], strict=True):
        require(request["model"] == condition["model"]
                and request["reasoning_effort"] == condition["reasoning_effort"]
                and request["control_profile"] == condition["control_profile"]
                and summary["model_dispatched"] is True
                and result["transport_receipt"]["dispatched"] is True
                and type(summary["total_tokens"]) is int
                and summary["total_tokens"] == result["transport_receipt"]["total_tokens"],
                "Model or usage differs from declared window")
        action = recorded_action(watch, request, result, row)
        for key in ("prompt_profile", "bindings_sha256", "max_advance_ticks"):
            require(request.get(key) == condition.get(key), "Recorded model condition differs")
        clock, after = row["tick_advance"], row["state_after_advance"]
        frames.append({
            "decision": row["step"] + 1, "screen": watch.screen_projection(request["screen"]),
            "action": watch.action_projection(action), "accepted": row["execute"]["accepted"],
            "before": {"year": clock["start_year"], "tick": clock["start_tick"]},
            "after": {"year": after["year"], "tick": after["year_tick"],
                      "population": after["population"], "ticks_advanced": clock["ticks_advanced"]},
        })
        tokens += summary["total_tokens"]
    require(tokens == proof["window_returned_tokens"] == owner["known_returned_tokens"],
            "Window token total differs")
    return frames, condition, manifest


def export(attempts: list[Path], audit_path: Path, expected_sha: str,
           *, identity: str, title: str) -> dict:
    require(re.fullmatch(r"[a-z0-9-]{1,100}", identity) is not None, "Invalid recording identity")
    watch.label(title, 160)
    require(sha(audit_path) == expected_sha, "Audit digest differs")
    audit = read(audit_path)
    require(audit.get("schema_version") in ("fortgym.portable-owner-continuity-audit/v1", RUN_AUDIT_SCHEMA)
            and audit.get("passed") is True
            and len(attempts) == len(audit["windows"]) and 1 <= len(attempts) <= 16,
            "Matching successful public-owner audit required")
    frames, previous, condition = [], None, None
    for attempt, proof in zip(attempts, audit["windows"], strict=True):
        checks: tuple[str, ...] = (
            "checkpoint_verified", "memory_usage_and_history_preserved",
            "original_inputs_unchanged", "native_cleanup_verified",
            "container_stopped_verified")
        if audit["schema_version"] == RUN_AUDIT_SCHEMA:
            require(audit.get("vm_teardown_audited") is False
                    and audit.get("current_container_state_observed") is False,
                    "Run audit cannot claim current engine or VM observation")
            checks += ("recorded_resource_and_isolation_limits_verified",)
            verify_artifact_hashes(attempt, proof.get("artifact_sha256"))
        else:
            # Keep the original acceptance's two-VM promises unchanged.
            checks += ("both_vms_stopped", "both_vm_disks_closed")
        require(all(proof.get(key) is True for key in checks),
            "Window lacks audited continuity/teardown")
        added, selected, manifest = export_window(attempt, audit, proof)
        require(condition is None or selected == condition, "Recording changes model condition")
        if previous is not None:
            require(manifest["payload"]["parent_sha256"] == previous["sha256"]
                    and added[0]["decision"] == frames[-1]["decision"] + 1,
                    "Recording windows are not consecutive own saves")
        frames.extend(added)
        condition, previous = selected, manifest
    require(0 < len(frames) <= 1024, "Recording frame bound exceeded")
    assert condition is not None
    return {
        "schema_version": "fortgym.watch-recording/v1", "id": identity, "title": title,
        "model": condition["model"], "control_profile": condition["control_profile"],
        "first_decision": frames[0]["decision"], "last_decision": frames[-1]["decision"],
        "saved_through_decision": frames[-1]["decision"], "audit_sha256": expected_sha,
        "source_revision": audit["source_revision"], "recording_status": "saved", "frames": frames,
    }
