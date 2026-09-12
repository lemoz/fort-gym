"""Audit ordinary settled portable-owner runs from retained files only.

No Docker, VM, model, native input or publication operation is performed.
The output proves the recorded save/receipt chain, not current machine state
or autonomous fortress success. Failures remain in their original owner files.
"""

from pathlib import Path
import json
import re

from ..agent.keyboard_exchange import digest, read
from .campaign_checkpoint import verify_checkpoint
from .keyboard_docker_audit_contract import SCHEMA, artifact_hashes, verify_artifact_hashes
from .keyboard_docker_native_audit import audit_native
from .keyboard_docker_owner import owned_container
from .keyboard_docker_plan import SECCOMP_SCHEMA, absolute_path, prepare_inputs, validate_runtime
from .keyboard_docker_recording import export_window, receipts, require, sha


def verify_container_limits(container: dict, plan: dict, attempt: Path) -> None:
    """Check the retained inspection, not the engine's current configuration."""
    runtime, host = plan["runtime"], container["HostConfig"]
    for key, expected in {
        "Memory": runtime["memory_mib"] * 1024**2,
        "MemorySwap": runtime["memory_mib"] * 1024**2,
        "NanoCpus": runtime["cpus"] * 10**9,
        "PidsLimit": runtime["pids_limit"],
    }.items():
        require(
            type(host.get(key)) is int and host[key] == expected,
            "Recorded container resource limit differs",
        )
    arguments = plan["create_arguments"]
    user = arguments[arguments.index("--user") + 1]
    require(
        re.fullmatch(r"[1-9][0-9]*:[0-9]+", user) is not None
        and container["Config"].get("User") == user
        and host.get("ReadonlyRootfs") is True
        and host.get("Init") is True
        and host.get("NetworkMode") == "none"
        and host.get("CapDrop") == ["ALL"]
        and host.get("Privileged") is False
        and host.get("PublishAllPorts") is False
        and host.get("CapAdd") in (None, [])
        and host.get("Devices") == []
        and host.get("DeviceRequests") in (None, [])
        and host.get("PidMode") == ""
        and host.get("IpcMode") == "private"
        and host.get("PortBindings") == {},
        "Recorded container isolation differs",
    )
    security = host["SecurityOpt"]
    if runtime["schema_version"] == SECCOMP_SCHEMA:
        policies = [value for value in security if value.startswith("seccomp=")]
        require(
            len(policies) == 1 and json.loads(policies[0][8:]) == read(attempt / "seccomp.json"),
            "Recorded seccomp policy differs from retained bytes",
        )
        security = [value for value in security if not value.startswith("seccomp=")]
    require(security == ["no-new-privileges"], "Recorded privilege configuration differs")
    mounts = container["Mounts"]
    require(
        len(mounts) == 3
        and all(row.get("Type") == "bind" for row in mounts)
        and {row["Destination"]: row["RW"] for row in mounts}
        == {"/fortgym-evidence": True, "/fortgym-config": False, "/fortgym-origin": False}
        and all(type(row["RW"]) is bool for row in mounts),
        "Recorded container mount access differs",
    )


def input_paths(attempt: Path) -> tuple[Path, Path]:
    paths = list((attempt / "inputs").glob("*.json"))
    selected = [
        path
        for path in paths
        if read(path).get("schema_version", "").startswith("fortgym.codex-keyboard-condition/")
    ]
    require(len(paths) == 2 and len(selected) == 1, "Owner inputs are missing or ambiguous")
    return selected[0], next(path for path in paths if path != selected[0])


def evidence_paths(attempt: Path, segments: int) -> list[Path]:
    paths = [
        attempt / name
        for name in (
            "owner-plan.json",
            "owner-result.json",
            "container-stopped.json",
            "model-admission.json",
        )
    ]
    paths.extend((attempt / "inputs").glob("*.json"))
    native = attempt / "game/native"
    paths.extend(native / name for name in ("condition.json", "result.json"))
    paths.append(
        native
        / ("trial.json" if read(attempt / "owner-plan.json")["mode"] == "fresh" else "window.json")
    )
    if (attempt / "seccomp.json").exists():
        paths.append(attempt / "seccomp.json")
    for index in range(segments):
        segment = native / f"segment-{index}"
        paths.append(native / f"runtime-{index}/result.json")
        paths.extend(
            segment / name
            for name in (
                "result.json",
                "agent-before.json",
                "agent-after.json",
                "history-before.json",
                "native-before.json",
                "native-after.json",
                "initial-screen.json",
            )
        )
        if (segment / "origin.json").exists():
            paths.append(segment / "origin.json")
        paths.extend(
            segment / "checkpoint" / name
            for name in (
                "checkpoint.json",
                "agent.json",
                "runner.json",
                "trace.jsonl",
                "usage.jsonl",
            )
        )
        paths.extend(segment / "loop" / name for name in ("trace.jsonl", "usage.jsonl"))
    folders = list((attempt / "model").iterdir())
    require(
        all(path.is_dir() and re.fullmatch(r"[a-f0-9]{32}", path.name) for path in folders),
        "Unexpected model receipt entry",
    )
    for folder in folders:
        paths.extend(
            folder / name
            for name in ("request.json", "response.json", "summary.json", "claim.json")
        )
        paths.extend(
            native / "exchange" / folder.name / name for name in ("request.json", "response.json")
        )
    return paths


def audit_window(attempt: Path, origin: Path) -> tuple[dict, dict]:
    absolute_path(attempt)
    absolute_path(origin)
    plan, owner = read(attempt / "owner-plan.json"), read(attempt / "owner-result.json")
    native = read(attempt / "game/native/result.json")
    require(
        plan.get("schema_version") == "fortgym.keyboard-docker-owner-plan/v1"
        and owner.get("schema_version") == "fortgym.keyboard-docker-owner-result/v1"
        and plan.get("mode") in ("fresh", "continue")
        and owner.get("mode") == plan["mode"]
        and owner.get("status") == "execution_finished"
        and owner.get("container_create_attempted") is True
        and owner.get("original_inputs_unchanged") is True
        and owner.get("container_stopped_verified") is True
        and not any(k.endswith("error") or k.endswith("error_type") for k in owner)
        and owner.get("native_result") == native,
        "Owner has no settled saved window; retain its original outcome",
    )
    segments = [native["segment"]] if plan["mode"] == "fresh" else native["segments"]
    require(
        isinstance(segments, list) and 1 <= len(segments) <= 16,
        "Missing or oversized native segment sequence",
    )
    hashes = artifact_hashes(attempt, evidence_paths(attempt, len(segments)))
    require(
        read(attempt / "owner-plan.json") == plan and read(attempt / "owner-result.json") == owner,
        "Owner inputs changed during audit",
    )
    condition_path, declaration_path = input_paths(attempt)
    inputs = prepare_inputs(
        condition_path, declaration_path, origin, plan["campaign_id"], mode=plan["mode"]
    )
    require(
        digest(inputs["condition"]) == plan["condition_sha256"]
        and digest(inputs["declaration"]) == plan["declaration_sha256"]
        and digest(inputs["original"]) == plan["original_verified_record_sha256"]
        and type(plan["response_limit"]) is int
        and plan["response_limit"] == inputs["limit"],
        "Owner plan differs from its actual origin or declarations",
    )
    runtime = plan["runtime"]
    # A moved capture uses the retained policy bytes, not an old host pathname.
    validation_runtime = (
        {**runtime, "seccomp_profile": str(attempt / "seccomp.json")}
        if runtime["schema_version"] == SECCOMP_SCHEMA
        else runtime
    )
    validate_runtime(validation_runtime)
    require(
        owner["source_revision"] == native["source_revision"] == runtime["source_revision"]
        and owner["campaign_id"] == native["campaign_id"] == plan["campaign_id"]
        and owner["image"] == runtime["image"]
        and owner.get("seccomp_sha256") == runtime.get("seccomp_sha256")
        and read(attempt / "model-admission.json").get("allowed") is True,
        "Owner/runtime identity or recorded admission differs",
    )
    stopped = read(attempt / "container-stopped.json")
    require(
        owned_container(stopped, runtime, plan["owner_nonce"]) == owner["container_id"]
        and stopped["State"]["Running"] is False
        and type(stopped["State"].get("ExitCode")) is int
        and stopped["State"]["ExitCode"] == 0
        and stopped["State"].get("OOMKilled") is False,
        "Owned container lacks a clean recorded stop",
    )
    verify_container_limits(stopped, plan, attempt)
    reports = audit_native(attempt / "game/native", origin, inputs, runtime["source_revision"])
    final = reports[-1]
    checkpoint = attempt / f"game/native/segment-{len(reports) - 1}/checkpoint"
    manifest = verify_checkpoint(checkpoint)
    state = read(checkpoint / "agent.json")
    proof = {
        "mode": plan["mode"],
        "native_status": native["status"],
        "first_step": reports[0]["first_step"],
        "next_step": final["next_step"],
        "new_model_responses": sum(row["new_responses"] for row in reports),
        "window_returned_tokens": sum(row["new_tokens"] for row in reports),
        "cumulative_returned_tokens": state["usage"]["total_tokens"],
        "checkpoint_manifest_sha256": manifest["sha256"],
        "checkpoint_file_sha256": sha(checkpoint / "checkpoint.json"),
        "parent_manifest_sha256": reports[0]["prior_checkpoint_sha256"],
        "owner_result_sha256": hashes["owner-result.json"],
        "native_result_sha256": hashes["game/native/result.json"],
        "container_inspection_sha256": hashes["container-stopped.json"],
        "checkpoint_verified": True,
        "original_inputs_unchanged": True,
        "native_cleanup_verified": True,
        "container_stopped_verified": True,
        "recorded_resource_and_isolation_limits_verified": True,
        "memory_usage_and_history_preserved": False,
        "final_fresh_reload_verified": False,
        "saved_elapsed_ticks": final["saved_elapsed_ticks"],
        "new_saved_ticks": sum(row["new_saved_ticks"] for row in reports),
        "inherited_discontinuities": final["inherited_discontinuities"],
        "uninterrupted_campaign": final["uninterrupted_campaign"],
        "initial_metrics": reports[0]["initial_metrics"],
        "saved_metrics": final["saved_metrics"],
        "segments": reports,
        "reported_charge_usd": owner.get("reported_charge_usd"),
    }
    require(
        owner.get("responses_with_unknown_tokens") == 0
        and owner.get("reported_charge_usd", "missing") is None
        and proof["new_model_responses"] > 0,
        "A saved replay needs settled returned usage and at least one new decision",
    )
    audit_identity = {
        "campaign_id": plan["campaign_id"],
        "source_revision": runtime["source_revision"],
        "image": runtime["image"],
    }
    # Reuse the publication verifier for request/claim/action/native-trace binding.
    export_window(attempt, audit_identity, proof)
    memory = inputs["initial_memory"]
    entries = receipts(attempt)
    for summary, request, result in entries:
        folder = attempt / "model" / request["request_id"]
        exchange = attempt / "game/native/exchange" / request["request_id"]
        require(
            request["memory"] == memory
            and [request["screen"]["width"], request["screen"]["height"]]
            == inputs["condition"]["screen_size"]
            and read(exchange / "request.json") == request
            and read(exchange / "response.json") == read(folder / "response.json"),
            "Model memory or native response handoff differs",
        )
        if result.get("action") is not None:
            memory = result["action"]["memory_update"]
    require(memory == state["memory"], "Checkpoint omitted the last accepted memory update")
    proof["memory_usage_and_history_preserved"] = True
    require(
        prepare_inputs(
            condition_path, declaration_path, origin, plan["campaign_id"], mode=plan["mode"]
        )
        == inputs,
        "Original snapshot/checkpoint changed during audit",
    )
    require(verify_checkpoint(checkpoint) == manifest, "Final checkpoint changed during audit")
    verify_artifact_hashes(attempt, hashes)
    proof["artifact_sha256"] = hashes
    return proof, {**audit_identity, "condition_sha256": plan["condition_sha256"]}


def audit(attempts: list[tuple[Path, Path]]) -> dict:
    """Audit ordered own-save windows; the origin is explicit for each window."""
    require(1 <= len(attempts) <= 16, "Audit one to sixteen declared windows")
    require(
        len({attempt.resolve() for attempt, _ in attempts}) == len(attempts),
        "An owner attempt cannot be repeated",
    )
    reports: list[dict] = []
    identity = None
    for attempt, origin in attempts:
        report, selected = audit_window(attempt, origin)
        require(
            identity is None or identity == selected, "Run chain changes model/source conditions"
        )
        if reports:
            require(
                report["mode"] == "continue"
                and report["parent_manifest_sha256"] == reports[-1]["checkpoint_manifest_sha256"]
                and report["first_step"] == reports[-1]["next_step"],
                "Run windows are not consecutive own-save continuations",
            )
            reports[-1]["final_fresh_reload_verified"] = True
        reports.append(report)
        identity = selected
    assert identity is not None
    return {
        "schema_version": SCHEMA,
        "passed": True,
        **identity,
        "windows": reports,
        "model_responses": sum(row["new_model_responses"] for row in reports),
        "known_returned_tokens": sum(row["window_returned_tokens"] for row in reports),
        "cumulative_returned_tokens": reports[-1]["cumulative_returned_tokens"],
        "reported_charge_usd": None,
        "cost_basis": "codex_subscription_charge_unreported/v1",
        "vm_teardown_audited": False,
        "current_container_state_observed": False,
        "scope": "Retained native saves, semantic v4 boundaries, owned-container stop/resource receipts, model usage and memory/action history. No live engine/VM check, full syscall policy audit, deployment, or gameplay-success inference.",
        "auditor_source_sha256": {
            path.name: sha(path)
            for path in (
                Path(__file__),
                Path(__file__).with_name("keyboard_docker_native_audit.py"),
                Path(__file__).with_name("keyboard_docker_audit_contract.py"),
            )
        },
        "model_calls": 0,
        "gameplay_inputs": 0,
        "docker_calls": 0,
        "website_published": False,
        "long_term_performance_verified": False,
    }
