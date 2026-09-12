"""Project retained intermediate audits without treating them as final results."""

import hashlib
from pathlib import Path
import re

from fort_gym.bench.agent.keyboard_exchange import read
from fort_gym.bench.run.campaign_checkpoint import _json_bytes

EVIDENCE = (
    "checkpoint.json",
    "first-after.json",
    "first-before.json",
    "first-history.json",
    "first-result.json",
    "first-runtime.json",
    "saved-agent.json",
    "second-agent.json",
    "second-before.json",
    "second-history.json",
)
PENDING = (
    "native_save_inventory_independently_copied",
    "full_trace_independently_audited",
    "full_window_completed",
    "owner_teardown_verified",
    "sustainability_established",
)


def file_sha(path: Path) -> str:
    # Use the same bounded regular-file check as the receipt reader.
    read(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def latest_boundary(run_dir: Path, base: dict, entries: list) -> dict | None:
    """Bind an existing auditor's claim to its metadata and this receipt prefix.

    This is not a second native-save inventory or canonical-trace audit. Those
    are intentionally still pending until the owner exports the final run.
    """
    paths = list(run_dir.glob("segment-boundary-*-review.json"))
    if not paths:
        return None
    if len(paths) >= base["max_segments"]:
        raise ValueError("Too many intermediate boundary reports")
    indices = []
    for path in paths:
        match = re.fullmatch(r"segment-boundary-(0|[1-9][0-9]*)-review.json", path.name)
        if match is None:
            raise ValueError("Invalid boundary report name")
        indices.append(int(match[1]))
    if sorted(indices) != list(range(len(paths))):
        raise ValueError("Boundary reports must form a consecutive chain")
    parent = base["initial_checkpoint_sha256"]
    previous_elapsed = base["saved_elapsed_ticks"]
    latest = None
    for index in sorted(indices):
        path = run_dir / f"segment-boundary-{index}-review.json"
        report = read(path)
        count = (index + 1) * base["steps_per_segment"]
        # A new audit can race this snapshot's earlier receipt scan. Keep the
        # previous boundary until the next scan includes the reload response.
        if len(entries) <= count:
            break
        if (
            report.get("schema_version") != "fortgym.private-native-segment-boundary/v1"
            or report.get("passed") is not True
            or type(report.get("segment_index")) is not int
            or report["segment_index"] != index
            or report.get("source_revision") != base["source_revision"]
            or report.get("first_runtime_cleanup_verified") is not True
            or report.get("second_worker_state_and_memory_match_save") is not True
            or any(report.get(key) is not False for key in PENDING)
        ):
            raise ValueError("Boundary audit does not match this live run")
        evidence = run_dir / f"segment-boundary-{index}-evidence"
        if evidence.is_symlink() or set(report["source_sha256"]) != set(EVIDENCE):
            raise ValueError("Boundary evidence set differs")
        for name in EVIDENCE:
            if file_sha(evidence / name) != report["source_sha256"][name]:
                raise ValueError("Retained boundary evidence changed")
        checkpoint = read(evidence / "checkpoint.json")
        result = read(evidence / "first-result.json")
        agent = read(evidence / "saved-agent.json")
        usage = agent["usage"]
        request_id = entries[count][0]["request_id"]
        if re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", request_id) is None:
            raise ValueError("Invalid boundary request identifier")
        request_path = run_dir / "attempt/model" / request_id / "request.json"
        if (
            checkpoint["sha256"] != report["checkpoint_sha256"]
            or hashlib.sha256(_json_bytes(checkpoint["payload"])).hexdigest()
            != checkpoint["sha256"]
            or checkpoint["payload"]["agent_sha256"]
            != report["source_sha256"]["saved-agent.json"]
            or checkpoint["payload"]["parent_sha256"] != parent
            or checkpoint["payload"]["next_step"]
            != base["saved_checkpoint_cursor"] + count
            or report["first_checkpoint_cursor"] != checkpoint["payload"]["next_step"]
            or report["checkpoint_file_sha256"]
            != report["source_sha256"]["checkpoint.json"]
            or result["source_revision"] != base["source_revision"]
            or result["committed_elapsed_ticks"]
            != report["first_segment_saved_elapsed_ticks"]
            or result["usage"] != usage
            or report["first_segment_usage"] != usage
            or usage["accounted_responses"] != base["campaign_responses"] + count
            or usage["total_tokens"]
            != base["campaign_tokens"]
            + sum(row[0]["total_tokens"] for row in entries[:count])
            or report["second_worker_first_request_sha256"] != file_sha(request_path)
            or entries[count][1]["memory"] != agent["memory"]
            or read(evidence / "second-agent.json") != agent
        ):
            raise ValueError("Boundary checkpoint or receipt prefix differs")
        elapsed = report["first_segment_saved_elapsed_ticks"]
        if type(elapsed) is not int or elapsed < previous_elapsed:
            raise ValueError("Saved elapsed time cannot move backwards")
        latest = {
            "checkpoint_cursor": report["first_checkpoint_cursor"],
            "elapsed_ticks": elapsed,
            "window_responses": count,
            "campaign_tokens": usage["total_tokens"],
            "report_sha256": file_sha(path),
            "checkpoint_sha256": report["checkpoint_sha256"],
            "evidence_basis": "audited_save_metadata_and_next_worker_reload",
            "full_inventory_and_trace_audit_complete": False,
        }
        parent, previous_elapsed = checkpoint["sha256"], elapsed
    return latest
