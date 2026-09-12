"""Synthetic provenance/observer contracts; real native proof lives in audited artifacts."""
import json
import subprocess
import sys
import time

import pytest

from fort_gym.bench.agent.keyboard_exchange import digest
from fort_gym.bench.api.watch import project_live
from fort_gym.bench.run import keyboard_docker_recording as recording
from fort_gym.bench.run import keyboard_docker_watch as live
from fort_gym.bench.run import keyboard_owner_process as processes
from tests.test_keyboard_binding_profile import condition, selected_request
from scripts import campaign_keyboard_docker_observe as observer


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


@pytest.fixture
def packet(tmp_path, monkeypatch):
    attempts, proofs, manifests = [], [], {}
    config = condition()
    for index, mode in enumerate(("fresh", "continue")):
        attempt = tmp_path / mode
        attempts.append(attempt)
        request = selected_request()
        request["screen"]["tile_order"] = "column_major"
        request["memory"] = "PRIVATE_MEMORY"
        action = {"type": "KEYSTROKE", "params": {"keys": ["d"]}, "advance_ticks": 0,
                  "intent": "Inspect the map", "memory_update": "PRIVATE_UPDATE"}
        response = {"request_sha256": digest(request), "result": {
            "action": action, "action_grammar_valid": True,
            "transport_receipt": {"dispatched": True, "total_tokens": 100}}}
        summary = {"decision_index": 0, "request_id": request["request_id"],
                   "model_dispatched": True, "total_tokens": 100}
        folder = attempt / "model" / request["request_id"]
        for name, value in (("request", request), ("response", response), ("summary", summary),
                            ("claim", {"request_sha256": digest(request)})):
            write(folder / (name + ".json"), value)
        native = {"campaign_id": "fixture", "source_revision": "a" * 40,
                  "runtime_cleanup_verified": True,
                  **({"segment": {}} if mode == "fresh" else {"segments": [{}]})}
        owner = {"campaign_id": "fixture", "source_revision": "a" * 40,
                 "image": "sha256:" + "b" * 64, "mode": mode, "status": "execution_finished",
                 "native_result": native, "container_stopped_verified": True,
                 "original_inputs_unchanged": True, "known_returned_tokens": 100,
                 "model_responses": [summary], "container_create_attempted": True,
                 "container_id": "c" * 64}
        declaration = {"schema_version": "fortgym.keyboard-fresh-trial/v1" if mode == "fresh"
                       else "fortgym.codex-keyboard-window/v1", "continuation_from_next_step": index}
        plan = {"schema_version": "fortgym.keyboard-docker-owner-plan/v1",
                "campaign_id": "fixture", "mode": mode, "condition_sha256": digest(config),
                "declaration_sha256": digest(declaration), "response_limit": 1,
                "owner_nonce": "d" * 32,
                "runtime": {"image": owner["image"], "source_revision": owner["source_revision"]}}
        write(attempt / "owner-plan.json", plan)
        write(attempt / "inputs/condition.json", config)
        write(attempt / "inputs/declaration.json", declaration)
        write(attempt / "owner-result.json", owner)
        write(attempt / "container-stopped.json", {
            "Id": owner["container_id"], "Image": owner["image"],
            "Config": {"Labels": {"org.fortgym.owner": plan["owner_nonce"]}},
            "State": {"Running": False},
        })
        write(attempt / "game/native/result.json", native)
        write(attempt / "game/native/condition.json", config)
        checkpoint = attempt / "game/native/segment-0/checkpoint"
        write(checkpoint / "checkpoint.json", {"fixture": index})
        write(checkpoint / "agent.json", {"usage": {"total_tokens": 100 * (index + 1)}})
        rows = [{"step": n, "action": action, "execute": {"accepted": True},
                 "tick_advance": {"start_year": 30, "start_tick": 10, "ticks_advanced": 0},
                 "state_after_advance": {"year": 30, "year_tick": 10, "population": 7}}
                for n in range(index + 1)]
        (checkpoint / "trace.jsonl").write_text("\n".join(json.dumps(row) for row in rows))
        manifest = {"sha256": str(index + 1) * 64, "payload": {
            "next_step": index + 1, "campaign_id": "fixture", "code_revision": "a" * 40,
            "parent_sha256": None if index == 0 else "1" * 64}}
        manifests[checkpoint] = manifest
        proof = {"mode": mode, "owner_result_sha256": recording.sha(attempt / "owner-result.json"),
                 "native_result_sha256": recording.sha(attempt / "game/native/result.json"),
                 "checkpoint_file_sha256": recording.sha(checkpoint / "checkpoint.json"),
                 "checkpoint_manifest_sha256": manifest["sha256"], "next_step": index + 1,
                 "new_model_responses": 1, "window_returned_tokens": 100,
                 "cumulative_returned_tokens": 100 * (index + 1)}
        proof.update({key: True for key in ("checkpoint_verified", "memory_usage_and_history_preserved",
            "original_inputs_unchanged", "native_cleanup_verified", "container_stopped_verified",
            "both_vms_stopped", "both_vm_disks_closed")})
        proofs.append(proof)
    monkeypatch.setattr(recording, "verify_checkpoint", lambda path: manifests[path])
    audit = {"schema_version": "fortgym.portable-owner-continuity-audit/v1", "passed": True,
             "campaign_id": "fixture", "source_revision": "a" * 40,
             "image": "sha256:" + "b" * 64, "windows": proofs}
    path = tmp_path / "audit.json"
    write(path, audit)
    return attempts, path, manifests


def export(packet):
    attempts, audit, _ = packet
    return recording.export(attempts, audit, recording.sha(audit), identity="fixture", title="Fixture")


def test_recording_preserves_offsets_and_excludes_private_memory(packet):
    value = export(packet)
    assert [frame["decision"] for frame in value["frames"]] == [1, 2]
    assert value["saved_through_decision"] == 2
    assert "PRIVATE" not in json.dumps(value) and "memory" not in json.dumps(value)
    assert all(frame["accepted"] for frame in value["frames"])


@pytest.mark.parametrize("field", ["owner_result_sha256", "native_result_sha256",
                                  "checkpoint_file_sha256", "checkpoint_manifest_sha256"])
def test_recording_rejects_changed_audited_inputs(packet, field):
    _, path, _ = packet
    audit = json.loads(path.read_text())
    audit["windows"][0][field] = "0" * 64
    write(path, audit)
    with pytest.raises(ValueError, match="differs"):
        export(packet)


def test_recording_rejects_different_parent_and_changed_choice(packet):
    attempts, _, manifests = packet
    checkpoint = attempts[1] / "game/native/segment-0/checkpoint"
    manifests[checkpoint]["payload"]["parent_sha256"] = "9" * 64
    with pytest.raises(ValueError, match="consecutive own saves"):
        export(packet)
    manifests[checkpoint]["payload"]["parent_sha256"] = "1" * 64
    response_path = next((attempts[0] / "model").glob("*/response.json"))
    response = json.loads(response_path.read_text())
    response["result"]["action"]["params"]["keys"] = ["q"]
    write(response_path, response)
    with pytest.raises(ValueError, match="choice and native trace differ"):
        export(packet)


def test_watch_uses_public_owner_paths_and_never_publishes_private_state(packet):
    attempts, _, _ = packet
    base = live.baseline(attempts[1])
    assert base["saved_checkpoint_cursor"] == 1
    assert live.terminal(attempts[1], base)
    now = int(time.time())
    value = live.snapshot(attempts[1], base, alive=False, now=now)
    assert value["status"] == "stopped" and value["frame"]["decision"] == 2
    assert value["frame"]["action_status"] == "chosen_not_execution_verified"
    assert "PRIVATE" not in json.dumps(value) and "owner_process" not in json.dumps(value)
    assert project_live(value, now=now + 31)["status"] == "stale"
    with pytest.raises(ValueError, match="outside original"):
        live.validate_output(attempts[1], attempts[1] / "public")


def test_watch_rejects_changed_plan_and_unverified_stop(packet):
    attempts, _, _ = packet
    attempt = attempts[0]
    base = live.baseline(attempt)
    container = json.loads((attempt / "container-stopped.json").read_text())
    container["State"]["Running"] = True
    write(attempt / "container-stopped.json", container)
    with pytest.raises(ValueError, match="stop is unverified"):
        live.terminal(attempt, base)
    plan = json.loads((attempt / "owner-plan.json").read_text())
    plan["response_limit"] = 2
    write(attempt / "owner-plan.json", plan)
    with pytest.raises(ValueError, match="plan changed"):
        live.snapshot(attempt, base, alive=True, now=int(time.time()))


def test_optional_process_inspection_failure_does_not_block_game_owner(monkeypatch):
    def denied(pid):
        raise PermissionError("sandbox")
    monkeypatch.setattr(processes, "process_identity", denied)
    value = processes.capture_owner_process()
    assert value["identity"] is None and value["observation_error"] == "PermissionError"


def test_follow_expires_on_observation_error_then_stops_on_pid_reuse(packet, monkeypatch):
    attempts, _, _ = packet
    attempt = attempts[0]
    path = attempt / "owner-plan.json"
    plan = json.loads(path.read_text())
    plan["owner_process"] = {"pid": 4321, "identity": "original owner identity"}
    write(path, plan)
    observed = iter(["original owner identity", "original owner identity",
                     PermissionError("inspection denied"), "different start identity"])

    def identity(pid):
        assert pid == 4321
        value = next(observed)
        if isinstance(value, Exception):
            raise value
        return value

    published, sleeps = [], []
    monkeypatch.setattr(observer, "process_identity", identity)
    monkeypatch.setattr(observer, "publish", lambda root, value: published.append(value))
    monkeypatch.setattr(observer.time, "sleep", sleeps.append)
    monkeypatch.setattr(sys, "argv", ["observe", "follow", "--attempt", str(attempt),
                                     "--public-dir", str(attempt.parent / "public")])
    observer.main()
    assert [value["owner_alive"] for value in published] == [True, False]
    assert published[-1]["status"] == "stopped"
    assert sleeps == [10, 10]


def test_follow_requires_bound_owner_identity(packet, monkeypatch):
    attempts, _, _ = packet
    monkeypatch.setattr(sys, "argv", ["observe", "follow", "--attempt", str(attempts[0]),
                                     "--public-dir", str(attempts[0].parent / "public")])
    with pytest.raises(ValueError, match="matching live process"):
        observer.main()


@pytest.mark.parametrize("returncode,stdout,expected", [(0, " owner identity \n", "owner identity"),
                                                       (1, "", None)])
def test_process_identity_distinguishes_matching_and_missing(monkeypatch, returncode, stdout, expected):
    def run(args, **kwargs):
        assert args == ["ps", "-p", "4321", "-o", "lstart=,command="]
        assert kwargs["timeout"] == 5
        return subprocess.CompletedProcess(args, returncode, stdout, "")
    monkeypatch.setattr(processes.subprocess, "run", run)
    assert processes.process_identity(4321) == expected


@pytest.mark.parametrize("returncode", [1, 2])
def test_process_identity_does_not_treat_inspection_failure_as_death(monkeypatch, returncode):
    monkeypatch.setattr(processes.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args, returncode, "", "inspection failed"))
    with pytest.raises(RuntimeError, match="unavailable"):
        processes.process_identity(4321)
