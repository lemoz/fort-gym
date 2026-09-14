"""Prepare the next bounded window from an audited portable campaign.

This is offline planning, not admission, current-VM teardown verification, a
runtime migration, or authorization to spend. No game/model operation occurs.
"""

from pathlib import Path

from ..agent.campaign_budget import effective_budget
from ..agent.keyboard_exchange import read
from .campaign_checkpoint import verify_checkpoint
from .keyboard_config import positive
from .keyboard_docker_audit import audit, input_paths
from .keyboard_docker_audit_contract import verify_artifact_hashes
from .keyboard_docker_plan import absolute_path, validate_runtime
from .keyboard_docker_recording import require, sha
from .keyboard_window_budget import WINDOW_V2, limits, verify_checkpoint_budget
from .keyboard_window_courier import window_bounds


def prepare_window(
    attempt: Path, origin: Path, runtime: dict, *, target_budget: dict, steps: int = 64
) -> tuple[dict, Path, Path]:
    """Return a v2 declaration and its unchanged condition/checkpoint paths."""
    absolute_path(attempt)
    absolute_path(origin)
    positive(steps, "endurance window size", maximum=64)
    target = limits(target_budget)
    validate_runtime(runtime)
    report = audit([(attempt, origin)])
    proof = report["windows"][0]
    prior = read(attempt / "owner-plan.json")
    # A retained seccomp file may move, but its digest and every other runtime
    # field must stay identical. A new source/image requires a separate protocol.
    current_runtime = {k: v for k, v in runtime.items() if k != "seccomp_profile"}
    prior_runtime = {k: v for k, v in prior["runtime"].items() if k != "seccomp_profile"}
    require(
        current_runtime == prior_runtime,
        "Endurance continuation must preserve the prior source/image and resources",
    )
    condition_path, previous_declaration_path = input_paths(attempt)
    condition, declaration = read(condition_path), read(previous_declaration_path)
    native = read(attempt / "game/native/result.json")
    segments = [native["segment"]] if prior["mode"] == "fresh" else native["segments"]
    checkpoint = attempt / f"game/native/segment-{len(segments) - 1}/checkpoint"
    manifest = verify_checkpoint(checkpoint)
    require(
        manifest["sha256"] == proof["checkpoint_manifest_sha256"],
        "Audited checkpoint changed while preparing continuation",
    )
    state = read(checkpoint / "agent.json")
    before = effective_budget(
        state["configuration"], state.get("budget_extensions", []), state["usage"]
    )
    require(
        all(target[k] >= before[k] for k in before),
        "Endurance target cannot reduce an inherited cumulative limit",
    )
    cursor = manifest["payload"]["next_step"]
    require(type(cursor) is int and cursor > 0, "A continuation needs a settled decision")
    require(cursor < target["max_dispatches"], "Declared endurance dispatch budget exhausted")
    require(
        state["usage"]["total_tokens"] < target["max_total_tokens"],
        "Declared endurance token budget exhausted",
    )
    count = min(steps, target["max_dispatches"] - cursor)
    window = {
        "schema_version": WINDOW_V2,
        "condition_id": condition["condition_id"],
        "original_condition": condition_path.name,
        "continuation_checkpoint_sha256": manifest["sha256"],
        "continuation_from_next_step": cursor,
        "steps_per_segment": count,
        "max_segments": 1,
        "window_end_decision": cursor + count,
        "expected_campaign_id": report["campaign_id"],
        "source_native_revision": runtime["source_revision"],
        "source_image_id": runtime["image"],
        "source_condition_sha256": sha(condition_path),
        "source_result_sha256": sha(attempt / "game/native/result.json"),
        "accounted_responses_before_window": state["usage"]["accounted_responses"],
        "returned_tokens_before_window": state["usage"]["total_tokens"],
        "saved_elapsed_ticks_before_window": proof["saved_elapsed_ticks"],
        "reset_memory": False,
        "reset_usage": False,
        "strategy_intervention": False,
        "budget_before": before,
    }
    if target != before:
        window["budget_extension"] = target
    if "seccomp_sha256" in runtime:
        window["seccomp_sha256"] = runtime["seccomp_sha256"]
    for field in (
        "snapshot_profile",
        "runtime_rpc_transport",
        "private_measurement_profile",
        "private_measurement_timeout_seconds",
        "resource_observation_profile",
    ):
        if field in declaration:
            window[field] = declaration[field]
    verify_checkpoint_budget(state, window, manifest["sha256"])
    require(window_bounds(condition, window)[0] == count, "Prepared window bound differs")
    require(verify_checkpoint(checkpoint) == manifest, "Prepared checkpoint changed")
    verify_artifact_hashes(attempt, proof["artifact_sha256"])
    return window, condition_path, checkpoint
