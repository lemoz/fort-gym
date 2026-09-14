"""Audit one settled independent displayed-key fresh start; never infer model or fortress success."""

from collections import Counter
import importlib.util
import json
from pathlib import Path
import argparse
import re

BASE = Path(__file__).resolve().parent


def initialize():
    """Load the declared owner and native readers only for a requested audit."""
    global \
        owner_module, \
        sha, \
        read, \
        publish, \
        initial_usage, \
        digest, \
        read_campaign_progress
    global campaign_profile, metrics_from_state, verify_checkpoint, read_binding_index
    global \
        binding_event, \
        validate_measurement, \
        reconciled_usage, \
        verify_snapshot, \
        review_request
    spec = importlib.util.spec_from_file_location(
        "comparison_owner", BASE / "local_owner.py"
    )
    owner_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(owner_module)
    owner_module.initialize()
    sha, read, publish = owner_module.sha, owner_module.read, owner_module.publish
    from fort_gym.bench.agent.campaign_keyboard import initial_usage
    from fort_gym.bench.agent.keyboard_exchange import digest
    from fort_gym.bench.eval.campaign import read_campaign_progress
    from fort_gym.bench.eval.campaign_profile import (
        campaign_profile,
        metrics_from_state,
    )
    from fort_gym.bench.run.campaign_checkpoint import verify_checkpoint
    from fort_gym.bench.env.campaign_binding_keys import read_binding_index
    from fort_gym.bench.env.display_key_catalog import binding_event
    from fort_gym.bench.run.campaign_food import validate_measurement
    from fort_gym.bench.run.campaign_loop import reconciled_usage
    from scripts.campaign_load_smoke import verify_snapshot

    receipt = module(
        "comparison_receipt_review",
        BASE / "receipt_review.py",
        sha(BASE / "receipt_review.py"),
    )
    review_request = receipt.review_request


def module(name, path, expected):
    assert sha(path) == expected
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def verify_shape(result):
    assert result["status"] in {"completed", "paused"}
    segment = result["segment"]
    assert (
        segment["status"] == "bounded_segment_complete" and segment["first_step"] == 0
    )
    assert type(segment["next_step"]) is int and 1 <= segment["next_step"] <= 64
    if result["status"] == "completed":
        assert segment["next_step"] == 64 and segment["stop_reason"] == "segment_limit"
    else:
        assert (
            segment["next_step"] < 64
            and segment["stop_reason"] == "budget_limited_pause"
        )
    return segment


def verify_teardown(owner):
    """Require actual stopped proof; retain a disconnected guest shutdown command."""
    assert type(owner["guest_poweroff_returncode"]) is int
    assert 0 <= owner["guest_poweroff_returncode"] <= 255
    assert owner["vm_stop_returncode"] == 0 and owner["vm_observed_stopped"] is True
    return {
        "guest_poweroff_returncode": owner["guest_poweroff_returncode"],
        "vm_stop_returncode": 0,
        "vm_observed_stopped": True,
        "guest_command_warning": owner["guest_poweroff_returncode"] != 0,
    }


def main():
    row, condition = owner_module.selection()
    identity = row["campaign_id"]
    out = owner_module.SESSION / "attempt"
    native = out / "evidence/astra"
    segment_path = native / "segment-0"
    checkpoint = segment_path / "checkpoint"
    assert not (out / "terminal-review.json").exists()
    owner, result = read(out / "result.json"), read(native / "result.json")
    assert (
        owner["binding"]
        == read(owner_module.SESSION / "execution.json")
        == owner_module.binding()
    )
    assert (
        owner["source_revision"] == result["source_revision"] == owner_module.REVISION
    )
    assert owner["campaign_id"] == result["campaign_id"] == identity
    assert owner["native"] == result and owner["status"] == "terminal_pending_audit"
    assert not any("error" in k for k in owner)
    assert owner["image_id"] == owner_module.IMAGE
    assert (
        owner["model"] == condition["model"] and owner["reasoning_effort"] == "medium"
    )
    assert (
        owner["provider_calls_complete"]
        is owner["vm_observed_stopped"]
        is owner["vm_config_unchanged"]
        is True
    )
    assert (
        owner["cloud_vms_created"] == 0 and owner["reported_model_charge_usd"] is None
    )
    for key in (
        "container-stop",
        "container-log",
        "container-final-state",
        "evidence-copy",
    ):
        assert owner[key + "_returncode"] == 0
    shutdown = verify_teardown(owner)
    state = read(out / "container-final-state.log")
    assert (state["Running"], state["Pid"], state["ExitCode"], state["OOMKilled"]) == (
        False,
        0,
        0,
        False,
    )
    config = read(out / "container-config.json")
    host = config["HostConfig"]
    assert (
        host["Init"] is True
        and host["PidsLimit"] == 256
        and host["NetworkMode"] == "none"
    )
    assert (
        host["Memory"] == host["MemorySwap"] == 1610612736
        and host["NanoCpus"] == 2000000000
    )
    assert config["Config"]["Labels"]["fortgym.owner"] == "fort-gym-" + identity
    assert config["Image"] == owner_module.IMAGE
    assert any(
        m["Destination"] == "/seed-evidence" and m["RW"] is False
        for m in config["Mounts"]
    )
    segment = verify_shape(result)
    assert result["source_snapshot_receipt_sha256"] == owner_module.SEED_SHA
    assert all(
        result[k] is True
        for k in (
            "native_load_verified",
            "runtime_cleanup_verified",
            "source_snapshot_unchanged",
            "new_checkpoint_verified",
        )
    )
    runtime = read(native / "runtime-0/result.json")
    assert runtime["experiment"] == segment == read(segment_path / "result.json")
    assert (
        runtime["code_revision"] == segment["source_revision"] == owner_module.REVISION
    )
    assert runtime["source_snapshot_receipt_sha256"] == owner_module.SEED_SHA
    assert (
        runtime["native_load_verified"]
        is runtime["cleanup_verified"]
        is runtime["listener_closed"]
        is True
    )
    assert runtime["remaining_live_processes"] == []
    assert (
        segment["checkpoint_verified"] is True
        and segment["recovery_requires_reconciliation"] is False
    )
    assert segment.get("discontinuities", []) == []
    assert read(segment_path / "history-before.json") == {"discontinuities": []}
    initial = read(segment_path / "agent-before.json")
    assert (
        initial["campaign_id"] == identity
        and initial["usage"] == initial_usage()
        and initial["memory"] == ""
    )
    assert (
        segment["origin"]
        == read(segment_path / "origin.json")
        == {
            "kind": "independent_native_snapshot/v1",
            "source_snapshot_receipt_sha256": owner_module.SEED_SHA,
            "condition_sha256": digest(condition),
            "initial_memory": "empty",
            "borrowed_prior_campaign_usage": False,
        }
    )
    assert read(native / "condition.json") == condition
    manifest = verify_checkpoint(checkpoint)
    payload = manifest["payload"]
    count = segment["next_step"]
    assert payload["parent_sha256"] is None and payload["campaign_id"] == identity
    assert payload["next_step"] == count and payload["last_committed_step"] == count - 1
    agent = read(checkpoint / "agent.json")
    assert agent == read(segment_path / "agent-after.json")
    for key in ("configuration", "budget_extensions", "prompt_changes"):
        assert agent.get(key) == initial.get(key)
    for filename in ("trace.jsonl", "usage.jsonl"):
        assert sha(checkpoint / filename) == sha(segment_path / "loop" / filename)
    assert (
        reconciled_usage(agent, (checkpoint / "usage.jsonl").read_bytes())
        == agent["usage"]
        == segment["usage"]
    )
    assert (
        agent["usage"]["accounted_responses"]
        == agent["usage"]["dispatched_requests"]
        == count
    )
    folders = sorted(
        (p.parent for p in (out / "model").glob("*/summary.json")),
        key=lambda p: read(p / "summary.json")["decision_index"],
    )
    assert {p.name for p in folders} == {
        p.parent.name for p in (native / "exchange").glob("*/request.json")
    }
    assert {p.name for p in folders} == {
        p.parent.name for p in (out / "model").glob("*/claim.json")
    }
    assert owner["model_decisions"] == [read(p / "summary.json") for p in folders]
    pause = module(
        "matched_admission_pause",
        owner_module.RUNTIME
        / "astra-native-included-headroom-v1/receipt_pause_review.py",
        "57830e341774b2a5017a264955967fa9b0fb02d7ce4ad9ada7a065bb8364d6d8",
    )
    reviews, pauses, actions, memory = [], [], [], ""
    for i, folder in enumerate(folders):
        request, summary = read(folder / "request.json"), read(folder / "summary.json")
        decision = read(folder / "response.json")["result"]
        assert summary["decision_index"] == i and request["memory"] == memory
        assert (
            request["model"] == condition["model"]
            and request["reasoning_effort"] == "medium"
        )
        assert [request["screen"]["width"], request["screen"]["height"]] == [120, 40]
        for filename in ("request.json", "response.json"):
            assert read(folder / filename) == read(
                native / "exchange" / folder.name / filename
            )
        if summary["model_dispatched"] is True:
            reviews.append(review_request(folder, condition))
            actions.append(decision["action"])
            if decision["action_grammar_valid"]:
                memory = decision["action"]["memory_update"]
        else:
            assert i == len(folders) - 1 and result["status"] == "paused"
            pauses.append(pause.review_pause(folder))
    assert (
        len(reviews)
        == owner["provider_calls"]
        == owner["confirmed_model_calls"]
        == count
    )
    assert agent["memory"] == memory
    tokens = sum(r["total_tokens"] for r in reviews)
    assert (
        agent["usage"]["total_tokens"] == tokens
        and agent["usage"]["total_cost_usd"] is None
    )
    before, after = (
        read(segment_path / "native-before.json"),
        read(segment_path / "native-after.json"),
    )
    assert (before["year"], before["year_tick"], before["pause_state"]) == (
        30,
        16801,
        True,
    )
    assert (
        runtime["loaded"]["year"],
        runtime["loaded"]["year_tick"],
        runtime["loaded"]["paused"],
    ) == (30, 16801, True)
    assert after["pause_state"] is True
    save = payload["native_save"]
    assert save["snapshot_profile"] == "native_menu_preserving_save/v4"
    assert all(
        save[k] is True
        for k in ("paused", "ui_identity_unchanged", "world_observations_unchanged")
    )
    assert save["screen_unchanged"] is (
        save["screen_sha256"] == save["screen_after_sha256"]
    )
    assert (save["year"], save["year_tick"]) == (after["year"], after["year_tick"])
    elapsed = (after["year"] - 30) * 403200 + after["year_tick"] - 16801
    progress = read_campaign_progress(checkpoint / "trace.jsonl")
    assert (
        progress["elapsed_ticks"] == segment["committed_elapsed_ticks"] == elapsed >= 0
    )
    assert progress.get("native_save_loss_restarts", 0) == 0
    rows = [
        json.loads(line)
        for line in (checkpoint / "trace.jsonl").read_text().splitlines()
    ]
    assert [r["step"] for r in rows] == list(range(count))
    assert sum(r["tick_advance"]["ticks_advanced"] for r in rows) == elapsed
    assert not (segment_path / "loop/failures.jsonl").exists()
    index = read_binding_index(native / "runtime-0/runtime")
    tested_presses = 0
    food = []
    for record, action in zip(rows, actions, strict=True):
        assert record["run_id"] == identity
        if action is not None:
            assert record["action"] == action
        if action is not None:
            execution = record["execute"]
            receipt = execution["result"]
            assert execution["accepted"] is True
            assert receipt["control_profile"] == condition["control_profile"]
            assert (
                receipt["bindings_sha256"]
                == condition["bindings_sha256"]
                == index.sha256
            )
            keys = action["params"]["keys"]
            assert receipt["keys_sent"] == receipt["keys_confirmed"] == len(keys)
            assert len(receipt["native_receipts"]) == len(keys)
            for key, wrapper in zip(keys, receipt["native_receipts"]):
                events = list(index.resolve(binding_event(key)))
                assert wrapper["key"] == key and wrapper["events"] == events
                native_receipt = wrapper["receipt"]
                assert native_receipt["ok"] and native_receipt["events"] == events
                assert native_receipt["input_calls"] == 1
                assert native_receipt["command_mutation"] == "completed"
                a, b = native_receipt["before"], native_receipt["after"]
                assert a["paused"] is b["paused"] is True
                assert (a["year"], a["year_tick"], a["save_name"]) == (
                    b["year"],
                    b["year_tick"],
                    b["save_name"],
                )
                tested_presses += 1
        state = record["state_after_advance"]
        measure = validate_measurement(
            state["private_food_measurement"],
            year=state["year"],
            year_tick=state["year_tick"],
        )
        assert measure["read_timeout_seconds"] == 15
        food.append(measure)
    final_food = validate_measurement(
        after["private_food_measurement"],
        year=after["year"],
        year_tick=after["year_tick"],
    )
    profile = campaign_profile(
        rows,
        campaign_id=identity,
        status=segment["status"],
        usage=agent["usage"],
        terminal_state=after,
        initial_state=before,
    )
    activity_path = (
        owner_module.RUNTIME / "astra-year-two-continuation-v1/activity_review.py"
    )
    activity = module(
        "matched_activity",
        activity_path,
        "cd9cb1ad24b71b834736d5a379d0da05c07ff5191789c50f7993653000ef026b",
    ).review_trace(checkpoint / "trace.jsonl", 0, count)
    assert owner_module.stopped()
    verify_snapshot(
        owner_module.RUNTIME / "corrected-context/seed-smoke", owner_module.SEED_SHA
    )
    sources = [
        BASE / "local_owner.py",
        owner_module.SESSION / "execution.json",
        BASE / "receipt_review.py",
        out / "result.json",
        out / "container-final-state.log",
        out / "container-config.json",
        out / "guest-poweroff.log",
        out / "vm-stop.log",
        native / "result.json",
        native / "runtime-0/result.json",
        activity_path,
        *[
            segment_path / f
            for f in (
                "native-before.json",
                "native-after.json",
                "agent-before.json",
                "agent-after.json",
                "initial-screen.json",
                "final-screen.json",
                "result.json",
                "save-attempt.json",
            )
        ],
        *[
            checkpoint / f
            for f in (
                "checkpoint.json",
                "agent.json",
                "runner.json",
                "trace.jsonl",
                "usage.jsonl",
            )
        ],
    ]
    report = {
        "schema_version": "fortgym.private-binding-trial-terminal-review/v1",
        "passed": True,
        "campaign_id": identity,
        "model": condition["model"],
        "replicate": row["replicate"],
        "reasoning_effort": "medium",
        "source_revision": owner_module.REVISION,
        "image_id": owner_module.IMAGE,
        "status": result["status"],
        "stop_reason": segment["stop_reason"],
        "responses": count,
        "control_profile": condition["control_profile"],
        "confirmed_key_presses": tested_presses,
        "saved_elapsed_ticks": elapsed,
        "checkpoint_sha256": manifest["sha256"],
        "new_tokens": tokens,
        "usage": agent["usage"],
        "initial_metrics": metrics_from_state(before),
        "saved_metrics": metrics_from_state(after),
        "saved_food": final_food,
        "profile": profile,
        "observed_activity": activity,
        "food_complete_samples": sum(m["available"] for m in food),
        "food_samples": len(food),
        "clock_outcomes": dict(
            Counter(r["tick_advance"].get("error") or "no_error" for r in rows)
        ),
        "resource_observations": result["resource_observations"],
        "receipt_reviews": reviews,
        "admission_pauses": pauses,
        "native_cleanup_verified": True,
        "vm_teardown_verified": True,
        "shutdown": shutdown,
        "fresh_final_checkpoint_reload_verified": False,
        "repeated_new_condition_trials_complete": False,
        "human_gameplay_rescue": False,
        "sustainability_proven": False,
        "audit_source_sha256": sha(Path(__file__)),
        "sources": {str(p.relative_to(owner_module.ROOT)): sha(p) for p in sources},
    }
    publish(out / "terminal-review.json", report)
    print(
        json.dumps(
            {
                "passed": True,
                "campaign_id": identity,
                "responses": count,
                "saved_elapsed_ticks": elapsed,
                "tokens": tokens,
                "audit_sha256": sha(out / "terminal-review.json"),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--declaration-revision", required=True)
    arguments = parser.parse_args()
    if re.fullmatch(r"[a-f0-9]{40}", arguments.declaration_revision) is None:
        parser.error("Supply the exact pushed declaration revision")
    initialize()
    owner_module.TRIAL_ID = arguments.campaign_id
    owner_module.DECLARATION_REVISION = arguments.declaration_revision
    owner_module.selection()
    owner_module.SESSION = owner_module.BASE / owner_module.TRIAL_ID
    main()
