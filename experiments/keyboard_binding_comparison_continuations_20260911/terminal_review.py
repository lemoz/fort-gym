"""Audit a settled matched own-save window without game or provider calls."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

from continuation_state import (
    BASE,
    FRESH,
    ROOT,
    decision_started_bytes,
    inspect_origin,
    load_native,
    read,
    require,
    sha,
    verify_loaded_state,
)
from local_lifecycle import verify_container
from local_owner import specification
from rejection_review import review_rejection
from storage_amendment import verify_binding


def module(name: str, path: Path, expected: str) -> Any:
    require(sha(path) == expected, "Frozen review source changed")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def verify_teardown(control: dict) -> dict:
    require(not any("error" in key for key in control), "Owner retained an unresolved error")
    require(
        all(
            control.get(key) is True
            for key in (
                "provider_calls_complete",
                "vm_observed_stopped",
                "vm_config_unchanged",
                "original_checkpoint_verified_unchanged",
            )
        ),
        "Owner teardown or parent integrity is incomplete",
    )
    for tag in (
        "container-stop",
        "container-log",
        "container-final-state",
        "evidence-copy",
        "vm_stop",
    ):
        value = control.get(tag + "_returncode")
        require(type(value) is int and value == 0, "Unverified cleanup: " + tag)
    guest = control.get("guest_poweroff_returncode")
    require(type(guest) is int and 0 <= guest <= 255, "Missing guest shutdown observation")
    return {
        "guest_poweroff_returncode": guest,
        "guest_command_warning": guest != 0,
        "vm_stop_returncode": 0,
        "vm_observed_stopped": True,
    }


def verify_keys(
    record: dict, action: dict | None, condition: dict, index: Any, binding_event: Any
) -> int:
    require(
        action is not None,
        "Rejected responses require their typed receipt and no-dispatch proof",
    )
    require(record["action"] == action, "Trace action differs from model response")
    execution = record["execute"]
    assert action is not None
    require(execution["accepted"] is True, "Native input execution was not accepted")
    result, keys = execution["result"], action["params"]["keys"]
    require(
        result["control_profile"] == condition["control_profile"]
        and result["bindings_sha256"] == condition["bindings_sha256"] == index.sha256,
        "Native key binding profile differs",
    )
    require(
        type(result["keys_sent"]) is type(result["keys_confirmed"]) is int
        and result["keys_sent"] == result["keys_confirmed"] == len(keys)
        and len(result["native_receipts"]) == len(keys),
        "Native key counts differ",
    )
    for key, wrapper in zip(keys, result["native_receipts"], strict=True):
        events = list(index.resolve(binding_event(key)))
        receipt = wrapper["receipt"]
        require(
            wrapper["key"] == key
            and wrapper["events"] == events
            and receipt["events"] == events
            and receipt["ok"] is True
            and type(receipt["input_calls"]) is int
            and receipt["input_calls"] == 1
            and receipt["command_mutation"] == "completed",
            "Native key receipt differs",
        )
        before, after = receipt["before"], receipt["after"]
        require(
            before["paused"] is after["paused"] is True
            and all(before[k] == after[k] for k in ("year", "year_tick", "save_name")),
            "Native key receipt crossed an undeclared simulation boundary",
        )
    return len(keys)


def verify_input(
    record: dict,
    action: dict | None,
    folder: Path,
    condition: dict,
    index: Any,
    binding_event: Any,
) -> int:
    """Route a retained rejection through its original receipt, never a substitute move."""
    if action is None:
        return review_rejection(
            record,
            read(folder / "request.json"),
            read(folder / "response.json")["result"],
            condition,
        )
    return verify_keys(record, action, condition, index, binding_event)


def audit_window(native: Any, origin: dict, spec: dict) -> dict:
    from fort_gym.bench.run.keyboard_window_checkpoint_audit import (
        verify_window_checkpoints,
    )
    from fort_gym.bench.run.keyboard_window_receipts import verify_window_receipts

    owner, window, condition = native.owner, origin["window"], origin["condition"]
    identity, out = window["expected_campaign_id"], spec["session"] / "attempt"
    evidence = out / "evidence/astra"
    require(not (out / "terminal-review.json").exists(), "Never overwrite a terminal audit")
    control, result = read(out / "result.json"), read(evidence / "result.json")
    require(
        control["binding"] == read(spec["session"] / "execution.json") == spec["binding"],
        "Owner execution binding differs",
    )
    require(
        control["native"] == result and control["status"] == "terminal_pending_audit",
        "Window did not reach a settled auditable boundary",
    )
    require(
        control["source_revision"] == result["source_revision"] == owner.REVISION
        and control["image_id"] == owner.IMAGE
        and control["campaign_id"] == result["campaign_id"] == identity
        and control["model"] == condition["model"]
        and control["reasoning_effort"] == "medium"
        and control["first_step"] == 64
        and control["target_next_step"] == 128
        and control["cloud_vms_created"] == 0
        and control["reported_model_charge_usd"] is None,
        "Owner or native identity differs",
    )
    shutdown = verify_teardown(control)
    state = read(out / "container-final-state.log")
    require(
        (state["Running"], state["Pid"], state["ExitCode"], state["OOMKilled"])
        == (False, 0, 0, False),
        "Native container did not exit cleanly",
    )
    verify_container(read(out / "container-config.json"), spec)
    require(
        result["original_checkpoint_unchanged"] is result["runtime_cleanup_verified"] is True,
        "Native runtime cleanup or parent integrity failed",
    )
    fresh = module(
        "matched_fresh_review",
        FRESH / "terminal_review.py",
        "bcf9df58eaf8db74d51f8a9d73de184e69ea291544309ca483bb3f2f78a2c053",
    )
    fresh.initialize()
    pause = module(
        "matched_pause_review",
        owner.RUNTIME / "astra-native-included-headroom-v1/receipt_pause_review.py",
        "57830e341774b2a5017a264955967fa9b0fb02d7ce4ad9ada7a065bb8364d6d8",
    )
    activity = module(
        "matched_activity_review",
        owner.RUNTIME / "astra-year-two-continuation-v1/activity_review.py",
        "cd9cb1ad24b71b834736d5a379d0da05c07ff5191789c50f7993653000ef026b",
    )
    checks = verify_window_checkpoints(
        evidence,
        origin["checkpoint"],
        condition=condition,
        window=window,
        initial_metrics=origin["metrics"],
    )
    first, count = checks["first_step"], checks["next_step"]
    require(
        first == 64 and 64 <= count <= 128 and len(checks["segments"]) == 1,
        "Window does not match the declared common boundary",
    )
    receipts = verify_window_receipts(
        evidence,
        out,
        condition=condition,
        control=control,
        initial_memory=origin["agent"]["memory"],
        responses=count - first,
        status=result["status"],
        review_response=fresh.review_request,
        review_pause=pause.review_pause,
    )
    segment = evidence / "segment-0"
    checkpoint = segment / "checkpoint"
    agent = read(checkpoint / "agent.json")
    require(
        agent["memory"] == receipts["final_memory"]
        and agent["usage"] == checks["usage"]
        and receipts["new_tokens"] == checks["new_tokens"],
        "Final model usage or memory differs",
    )
    folders = sorted(
        (path.parent for path in (out / "model").glob("*/summary.json")),
        key=lambda path: read(path / "summary.json")["decision_index"],
    )
    require(bool(folders), "No initial exchange to verify the native load gate")
    prefixes = {}
    for filename in ("trace.jsonl", "usage.jsonl"):
        parent = (origin["checkpoint"] / filename).read_bytes()
        copied = (segment / "loop" / filename).read_bytes()
        require(copied.startswith(parent), "Native loop discarded its original prefix")
        if filename == "usage.jsonl":
            parent += decision_started_bytes(first)
            require(
                copied.startswith(parent),
                "Native loop changed its initial dispatch marker",
            )
        prefixes[filename] = hashlib.sha256(copied[: len(parent)]).hexdigest()
    gate = verify_loaded_state(
        origin,
        agent=read(segment / "agent-before.json"),
        history=read(segment / "history-before.json"),
        before=read(segment / "native-before.json"),
        prefix_sha256=prefixes,
        request=read(folders[0] / "request.json"),
        metrics=native.metrics,
    )
    require(
        read(out / "native-load-gate.json") == gate,
        "First-dispatch native-load gate differs",
    )
    rows = [json.loads(line) for line in (checkpoint / "trace.jsonl").read_text().splitlines()]
    require(
        [row["step"] for row in rows] == list(range(count)),
        "Canonical trace cursor differs",
    )
    index = fresh.read_binding_index(evidence / "runtime-0/runtime")
    presses, samples = 0, []
    for row, action, folder in zip(
        rows[first:], receipts["actions"], folders[: count - first], strict=True
    ):
        require(row["run_id"] == identity, "Trace includes another campaign")
        presses += verify_input(row, action, folder, condition, index, fresh.binding_event)
        after = row["state_after_advance"]
        sample = fresh.validate_measurement(
            after["private_food_measurement"],
            year=after["year"],
            year_tick=after["year_tick"],
        )
        require(sample["read_timeout_seconds"] == 15, "Private measurement profile changed")
        samples.append(sample)
    after = read(segment / "native-after.json")
    final_food = fresh.validate_measurement(
        after["private_food_measurement"],
        year=after["year"],
        year_tick=after["year_tick"],
    )
    original_before = read(origin["checkpoint"].parent / "native-before.json")
    profile = fresh.campaign_profile(
        rows,
        campaign_id=identity,
        status=result["segments"][-1]["status"],
        usage=agent["usage"],
        terminal_state=after,
        initial_state=original_before,
    )
    require(
        owner.stopped() and native.verify_checkpoint(origin["checkpoint"]) == origin["manifest"],
        "Owned VM still active or original checkpoint changed",
    )
    manifest = native.verify_checkpoint(checkpoint)
    require(manifest["sha256"] == checks["checkpoint_sha256"], "Final checkpoint changed")
    sources = [
        out / name
        for name in (
            "result.json",
            "launch.json",
            "container-config.json",
            "container-final-state.log",
            "guest-poweroff.log",
            "vm-stop.log",
            "native-load-gate.json",
        )
    ]
    sources += [
        evidence / "result.json",
        evidence / "condition.json",
        evidence / "window.json",
        evidence / "runtime-0/result.json",
        origin["checkpoint"] / "checkpoint.json",
    ]
    sources += [
        segment / name
        for name in (
            "result.json",
            "agent-before.json",
            "agent-after.json",
            "history-before.json",
            "native-before.json",
            "native-after.json",
            "save-attempt.json",
        )
    ]
    sources += [
        checkpoint / name
        for name in (
            "checkpoint.json",
            "agent.json",
            "runner.json",
            "trace.jsonl",
            "usage.jsonl",
        )
    ]
    report = {
        "schema_version": "fortgym.private-matched-window-terminal-review/v1",
        "passed": True,
        "campaign_id": identity,
        "model": condition["model"],
        "replicate": int(identity[-1]),
        "reasoning_effort": "medium",
        "source_revision": owner.REVISION,
        "image_id": owner.IMAGE,
        "status": result["status"],
        "stop_reason": result["segments"][-1]["stop_reason"],
        "first_step": first,
        "next_step": count,
        "responses": agent["usage"]["accounted_responses"],
        "new_responses": count - first,
        "new_tokens": receipts["new_tokens"],
        "usage": agent["usage"],
        "saved_elapsed_ticks": checks["saved_elapsed_ticks"],
        "new_saved_elapsed_ticks": checks["new_saved_ticks"],
        "source_checkpoint_sha256": origin["manifest"]["sha256"],
        "checkpoint_sha256": manifest["sha256"],
        "checkpoint_segments": checks["segments"],
        "confirmed_key_presses": presses,
        "initial_metrics": origin["metrics"],
        "saved_metrics": native.metrics(after),
        "saved_food": final_food,
        "profile": profile,
        "observed_activity": activity.review_trace(checkpoint / "trace.jsonl", first, count)
        if count > first
        else None,
        "food_samples": len(samples),
        "food_complete_samples": sum(sample["available"] for sample in samples),
        "clock_outcomes": dict(
            Counter(row["tick_advance"].get("error") or "no_error" for row in rows[first:])
        ),
        "resource_observations": result["resource_observations"],
        "receipt_reviews": receipts["receipt_reviews"],
        "admission_pauses": receipts["admission_pauses"],
        "native_cleanup_verified": True,
        "vm_teardown_verified": True,
        "shutdown": shutdown,
        "source_checkpoint_fresh_load_verified": True,
        "fresh_final_checkpoint_reload_verified": False,
        "human_gameplay_rescue": False,
        "sustainability_proven": False,
        "new_model_calls_by_auditor": 0,
        "new_game_ticks_by_auditor": 0,
        "audit_source_sha256": sha(Path(__file__)),
        "rejection_review_source_sha256": sha(BASE / "rejection_review.py"),
        "sources": {str(path.relative_to(ROOT)): sha(path) for path in sources},
    }
    if "storage_amendment" in spec["binding"]:
        report["storage_amendment"] = verify_binding(spec["binding"]["storage_amendment"], identity)
    owner.publish(out / "terminal-review.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", type=Path, required=True)
    parser.add_argument("--declaration-revision", required=True)
    parser.add_argument("--storage-amendment", type=Path)
    args = parser.parse_args()
    native = load_native()
    window_path = args.window.resolve(strict=True)
    require(window_path.parent == BASE.resolve(), "Select a declared matched window")
    origin = inspect_origin(ROOT, window_path, native)
    spec = specification(
        native, origin, window_path, args.declaration_revision, args.storage_amendment
    )
    report = audit_window(native, origin, spec)
    print(
        json.dumps(
            {
                "passed": True,
                "campaign_id": report["campaign_id"],
                "next_step": report["next_step"],
                "new_tokens": report["new_tokens"],
                "saved_elapsed_ticks": report["saved_elapsed_ticks"],
                "audit_sha256": sha(spec["session"] / "attempt/terminal-review.json"),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
