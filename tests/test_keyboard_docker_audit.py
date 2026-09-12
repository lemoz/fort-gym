"""Real checkpoint/agent machinery with synthetic Docker/model/native receipts."""

from copy import deepcopy
import json
import sys
import uuid

import pytest

from fort_gym.bench.agent.keyboard_exchange import digest, read
from fort_gym.bench.env.screen_observation import raw_screen
from fort_gym.bench.run import keyboard_docker_audit as audit_module
from fort_gym.bench.run import keyboard_docker_audit_contract as contract
from fort_gym.bench.run import keyboard_docker_native_audit as native_audit
from fort_gym.bench.run import keyboard_docker_recording as recording
from fort_gym.bench.run.campaign_checkpoint import CampaignCheckpointError, verify_checkpoint
from fort_gym.bench.run.keyboard_docker_plan import prepare_inputs
from fort_gym.bench.run.keyboard_segment import run_keyboard_segment
from fort_gym.bench.run.keyboard_trial import run_keyboard_trial
from scripts import campaign_keyboard_docker_audit as cli
from tests.test_campaign_codex_keyboard import decision
from tests.test_keyboard_docker_owner import RUNTIME
from tests.test_keyboard_fresh_trial import config, policy
from tests.test_keyboard_segment_audit import semantic_environment
from tests.test_keyboard_docker_spectator import packet as packet


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n")


def seed(directory):
    game = semantic_environment()
    directory.mkdir()
    snapshot = game.capture(directory / "native-snapshot")
    boundary = {"year": 30, "year_tick": game.tick, "paused": True}
    write(
        directory / "result.json",
        {
            "schema_version": "fortgym.native-save-smoke/v1",
            "native_snapshot_verified": True,
            "before": boundary,
            "after": boundary,
            "snapshot": snapshot,
        },
    )
    return directory


def run_fixture(attempt, origin, mode, *, model="gpt-6-astra", segments=1, token_limit=None):
    condition = config(model=model)
    if token_limit is not None:
        condition["max_total_tokens"] = token_limit
    native = attempt / "game/native"
    native.mkdir(parents=True)
    summaries = []
    campaign_id = "portable-audit-fixture"
    game = semantic_environment()
    if mode == "continue":
        game.tick = int((origin / "game/world.sav").read_text())
    loaded = {"year": 30, "year_tick": game.tick, "paused": True}
    condition_path = attempt / "inputs/condition.json"
    declaration_path = attempt / "inputs/declaration.json"
    declaration = {
        "schema_version": "fortgym.keyboard-fresh-trial/v1",
        "original_condition": condition_path.name,
        "source_snapshot_receipt_sha256": recording.sha(origin / "result.json")
        if mode == "fresh"
        else "",
        "steps_per_segment": 2,
        "initial_memory": "empty",
        "strategy_intervention": False,
        "snapshot_profile": "native_menu_preserving_save/v4",
        "runtime_rpc_transport": "native-rpc",
    }
    if mode == "continue":
        parent = verify_checkpoint(origin)
        declaration = {
            "schema_version": "fortgym.codex-keyboard-window/v1",
            "condition_id": condition["condition_id"],
            "original_condition": condition_path.name,
            "continuation_from_next_step": parent["payload"]["next_step"],
            "continuation_checkpoint_sha256": parent["sha256"],
            "steps_per_segment": 2,
            "max_segments": segments,
            "reset_memory": False,
            "reset_usage": False,
            "strategy_intervention": False,
            "snapshot_profile": "native_menu_preserving_save/v4",
            "runtime_rpc_transport": "native-rpc",
        }
    write(condition_path, condition)
    write(declaration_path, declaration)
    inputs = prepare_inputs(condition_path, declaration_path, origin, campaign_id, mode=mode)
    write(native / "condition.json", condition)
    write(native / ("trial.json" if mode == "fresh" else "window.json"), declaration)

    def model_response(screen, memory, feedback):
        value = decision(screen, memory, feedback)
        value["action"]["memory_update"] = memory + "PRIVATE_MODEL_MEMORY"
        value["prompt_profile"] = condition["prompt_profile"]
        value["transport_receipt"].update(model_requested=model)
        request = {
            "schema_version": "fortgym.keyboard-exchange-request/v3",
            "request_id": uuid.uuid4().hex,
            "screen": raw_screen(screen),
            "memory": memory,
            "feedback": feedback,
            **{
                key: condition[key]
                for key in (
                    "model",
                    "reasoning_effort",
                    "prompt_profile",
                    "control_profile",
                    "observation_profile",
                    "max_advance_ticks",
                )
            },
        }
        response = {"request_sha256": digest(request), "result": deepcopy(value)}
        summary = {
            "decision_index": len(summaries),
            "request_id": request["request_id"],
            "model_dispatched": True,
            "action_grammar_valid": True,
            "total_tokens": 100,
        }
        folder = attempt / "model" / request["request_id"]
        for name, data in (
            ("request", request),
            ("response", response),
            ("summary", summary),
            ("claim", {"request_sha256": digest(request)}),
        ):
            write(folder / (name + ".json"), data)
        for name, data in (("request", request), ("response", response)):
            write(native / "exchange" / request["request_id"] / (name + ".json"), data)
        summaries.append(summary)
        return value

    arguments = dict(
        agent=policy(condition, model_response),
        environment=game,
        snapshotter=game,
        output=native / "segment-0",
        condition=condition,
        steps=2,
        revision=RUNTIME["source_revision"],
    )
    if mode == "fresh":
        segment = run_keyboard_trial(
            **arguments,
            campaign_id=campaign_id,
            source_snapshot_receipt_sha256=declaration["source_snapshot_receipt_sha256"],
            loaded_boundary=loaded,
        )
        result = {
            "schema_version": "fortgym.keyboard-fresh-trial-result/v1",
            "native_load_verified": True,
            "new_checkpoint_verified": True,
            "source_snapshot_unchanged": True,
            "segment": segment,
            "source_snapshot_receipt_sha256": declaration["source_snapshot_receipt_sha256"],
        }
        binding = {"source_snapshot_receipt_sha256": declaration["source_snapshot_receipt_sha256"]}
    else:
        saved_segments = []
        parent = origin
        for index in range(segments):
            loaded = {"year": 30, "year_tick": game.tick, "paused": True}
            segment = run_keyboard_segment(
                **{
                    **arguments,
                    "agent": policy(condition, model_response),
                    "output": native / f"segment-{index}",
                },
                checkpoint=parent,
                latest_usage=parent / "usage.jsonl",
                expected_cursor=read(parent / "checkpoint.json")["payload"]["next_step"],
            )
            saved_segments.append(segment)
            write(
                native / f"runtime-{index}/result.json",
                {
                    "source_checkpoint_file_sha256": recording.sha(parent / "checkpoint.json"),
                    "experiment": segment,
                    "code_revision": RUNTIME["source_revision"],
                    "native_load_verified": True,
                    "cleanup_verified": True,
                    "listener_closed": True,
                    "remaining_live_processes": [],
                    "loaded": loaded,
                },
            )
            parent = native / f"segment-{index}/checkpoint"
            if segment["stop_reason"] != "segment_limit":
                break
        result = {
            "schema_version": "fortgym.keyboard-window-result/v1",
            "original_checkpoint_unchanged": True,
            "segments": saved_segments,
        }
        binding = {"source_checkpoint_file_sha256": recording.sha(origin / "checkpoint.json")}
    result.update(
        campaign_id=campaign_id,
        source_revision=RUNTIME["source_revision"],
        status="completed" if segment["stop_reason"] == "segment_limit" else "paused",
        runtime_cleanup_verified=True,
    )
    write(native / "result.json", result)
    if mode == "fresh":
        write(
            native / "runtime-0/result.json",
            {
                **binding,
                "experiment": segment,
                "code_revision": RUNTIME["source_revision"],
                "native_load_verified": True,
                "cleanup_verified": True,
                "listener_closed": True,
                "remaining_live_processes": [],
                "loaded": loaded,
            },
        )
    owner = {
        "schema_version": "fortgym.keyboard-docker-owner-result/v1",
        "mode": mode,
        "campaign_id": campaign_id,
        "source_revision": RUNTIME["source_revision"],
        "image": RUNTIME["image"],
        "native_result": result,
        "status": "execution_finished",
        "container_create_attempted": True,
        "container_stopped_verified": True,
        "original_inputs_unchanged": True,
        "container_id": "c" * 64,
        "responses_with_unknown_tokens": 0,
        "reported_charge_usd": None,
        "known_returned_tokens": 100 * len(summaries),
        "model_responses": summaries,
    }
    write(attempt / "owner-result.json", owner)
    write(
        attempt / "owner-plan.json",
        {
            "schema_version": "fortgym.keyboard-docker-owner-plan/v1",
            "mode": mode,
            "campaign_id": campaign_id,
            "runtime": RUNTIME,
            "owner_nonce": "d" * 32,
            "condition_sha256": digest(condition),
            "declaration_sha256": digest(declaration),
            "original_verified_record_sha256": digest(inputs["original"]),
            "response_limit": inputs["limit"],
            "create_arguments": ["create", "--user", "1000:1000"],
        },
    )
    write(attempt / "model-admission.json", {"allowed": True})
    write(
        attempt / "container-stopped.json",
        {
            "Id": owner["container_id"],
            "Image": owner["image"],
            "Config": {"Labels": {"org.fortgym.owner": "d" * 32}, "User": "1000:1000"},
            "State": {"Running": False, "ExitCode": 0, "OOMKilled": False},
            "HostConfig": {
                "Memory": RUNTIME["memory_mib"] * 1024**2,
                "MemorySwap": RUNTIME["memory_mib"] * 1024**2,
                "NanoCpus": RUNTIME["cpus"] * 10**9,
                "PidsLimit": RUNTIME["pids_limit"],
                "ReadonlyRootfs": True,
                "Init": True,
                "NetworkMode": "none",
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges"],
                "Privileged": False,
                "PublishAllPorts": False,
                "CapAdd": None,
                "Devices": [],
                "DeviceRequests": None,
                "PidMode": "",
                "IpcMode": "private",
                "PortBindings": {},
            },
            "Mounts": [
                {"Type": "bind", "Destination": destination, "RW": rw}
                for destination, rw in (
                    ("/fortgym-evidence", True),
                    ("/fortgym-config", False),
                    ("/fortgym-origin", False),
                )
            ],
        },
    )
    return (
        attempt,
        native / f"segment-{0 if mode == 'fresh' else len(saved_segments) - 1}/checkpoint",
    )


@pytest.fixture
def windows(tmp_path):
    original = seed(tmp_path / "seed")
    fresh, checkpoint = run_fixture(tmp_path / "fresh", original, "fresh")
    continuation, _ = run_fixture(tmp_path / "continue", checkpoint, "continue")
    return [(fresh, original), (continuation, checkpoint)]


def test_real_checkpoint_chain_exports_without_any_vm_assertion(windows, tmp_path):
    before = {
        p: p.read_bytes()
        for root in (windows[0][0], windows[0][1], windows[1][0])
        for p in root.rglob("*")
        if p.is_file()
    }
    report = audit_module.audit(windows)
    assert report["schema_version"] == contract.SCHEMA and report["passed"]
    assert report["model_responses"] == 4 and report["known_returned_tokens"] == 400
    assert report["cumulative_returned_tokens"] == 400 and report["reported_charge_usd"] is None
    assert [row["final_fresh_reload_verified"] for row in report["windows"]] == [True, False]
    assert report["windows"][-1]["saved_elapsed_ticks"] == 40
    assert report["vm_teardown_audited"] is False and report["docker_calls"] == 0
    assert "both_vms" not in json.dumps(report) and "PRIVATE_MODEL_MEMORY" not in json.dumps(report)
    path = tmp_path / "audit.json"
    write(path, report)
    result = recording.export(
        [row[0] for row in windows], path, recording.sha(path), identity="fixture", title="Fixture"
    )
    assert [row["decision"] for row in result["frames"]] == [1, 2, 3, 4]
    assert all(path.read_bytes() == data for path, data in before.items())


@pytest.mark.parametrize("model", ["gpt-6-astra", "gpt-5.6-sol", "gpt-5.6-terra"])
def test_fresh_run_selects_its_declared_model_without_calls(tmp_path, model):
    original = seed(tmp_path / "seed")
    attempt, _ = run_fixture(tmp_path / "run", original, "fresh", model=model)
    report = audit_module.audit([(attempt, original)])
    assert report["passed"] and report["model_calls"] == 0


@pytest.mark.parametrize(
    "file,field,value",
    [
        ("owner-result.json", "status", "failed"),
        ("owner-result.json", "original_inputs_unchanged", False),
        ("owner-result.json", "container_stopped_verified", False),
        ("owner-result.json", "known_returned_tokens", 0),
        ("owner-result.json", "image", "sha256:" + "0" * 64),
        ("owner-plan.json", "original_verified_record_sha256", "0" * 64),
        ("owner-plan.json", "response_limit", True),
        ("model-admission.json", "allowed", False),
    ],
)
def test_changed_owner_boundaries_are_rejected(windows, file, field, value):
    path = windows[0][0] / file
    data = read(path)
    data[field] = value
    write(path, data)
    with pytest.raises(ValueError):
        audit_module.audit(windows)


@pytest.mark.parametrize(
    "field,value", [("Running", True), ("ExitCode", 1), ("ExitCode", False), ("OOMKilled", True)]
)
def test_unverified_container_exit_is_not_a_saved_replay(windows, field, value):
    path = windows[0][0] / "container-stopped.json"
    data = read(path)
    data["State"][field] = value
    write(path, data)
    with pytest.raises(ValueError, match="recorded stop"):
        audit_module.audit(windows)


@pytest.mark.parametrize("relative", ["game/world.sav", "agent.json"])
def test_changed_final_agent_or_native_bytes_cannot_pass(windows, relative):
    path = windows[1][0] / "game/native/segment-0/checkpoint" / relative
    path.write_text("not the saved world")
    with pytest.raises(CampaignCheckpointError):
        audit_module.audit(windows)


def test_changed_native_handoff_is_rejected(windows):
    path = next((windows[0][0] / "game/native/exchange").glob("*/response.json"))
    data = read(path)
    data["result"]["action"]["memory_update"] = "DIFFERENT"
    write(path, data)
    with pytest.raises(ValueError, match="handoff"):
        audit_module.audit(windows)


def test_repeated_or_reversed_windows_do_not_invent_a_chain(windows):
    for selected in ([windows[0], windows[0]], list(reversed(windows))):
        with pytest.raises(ValueError):
            audit_module.audit(selected)


def test_replay_rechecks_the_new_audit_evidence_bindings(windows, tmp_path):
    path = tmp_path / "audit.json"
    write(path, audit_module.audit(windows))
    stopped = windows[0][0] / "container-stopped.json"
    data = read(stopped)
    data["State"]["Running"] = True
    write(stopped, data)
    with pytest.raises(ValueError, match="changed after"):
        recording.export(
            [row[0] for row in windows],
            path,
            recording.sha(path),
            identity="fixture",
            title="Fixture",
        )


@pytest.mark.parametrize("relative", ["../outside", "/outside", "a\\b"])
def test_audit_digest_paths_cannot_escape_the_attempt(tmp_path, relative):
    with pytest.raises(ValueError, match="path"):
        contract.verify_artifact_hashes(tmp_path, {relative: "a" * 64})


def test_cli_is_write_once_and_cannot_write_inside_a_retained_attempt(
    windows, tmp_path, monkeypatch
):
    output = tmp_path / "audit.json"
    args = ["audit", "--window", *map(str, windows[0]), "--output", str(output)]
    monkeypatch.setattr(sys, "argv", args)
    cli.main()
    before = output.read_bytes()
    with pytest.raises(FileExistsError):
        cli.main()
    assert output.read_bytes() == before
    args[-1] = str(windows[0][0] / "forbidden.json")
    monkeypatch.setattr(sys, "argv", args)
    with pytest.raises(ValueError, match="outside"):
        cli.main()


@pytest.mark.parametrize("key", ["both_vms_stopped", "both_vm_disks_closed"])
def test_legacy_two_vm_acceptance_contract_is_not_relaxed(packet, key):
    attempts, path, _ = packet
    data = read(path)
    data["windows"][0][key] = False
    write(path, data)
    with pytest.raises(ValueError, match="continuity/teardown"):
        recording.export(attempts, path, recording.sha(path), identity="fixture", title="Fixture")


@pytest.mark.parametrize(
    "field,value",
    [
        ("Memory", 512),
        ("MemorySwap", 0),
        ("NanoCpus", 0),
        ("PidsLimit", 1000),
        ("ReadonlyRootfs", False),
        ("Init", False),
        ("NetworkMode", "bridge"),
        ("CapDrop", []),
        ("SecurityOpt", []),
        ("Privileged", True),
        ("PublishAllPorts", True),
        ("CapAdd", ["SYS_ADMIN"]),
        ("Devices", [{"PathOnHost": "/dev/example"}]),
        ("DeviceRequests", [{"Count": -1}]),
        ("PidMode", "host"),
        ("IpcMode", "host"),
        ("PortBindings", {"80/tcp": [{"HostPort": "8000"}]}),
    ],
)
def test_resource_or_isolation_changes_cannot_be_reported_as_declared(windows, field, value):
    path = windows[0][0] / "container-stopped.json"
    data = read(path)
    data["HostConfig"][field] = value
    write(path, data)
    with pytest.raises(ValueError):
        audit_module.audit(windows)


def test_borrowed_initial_prompt_is_rejected(windows):
    path = windows[0][0] / "game/native/segment-0/agent-before.json"
    data = read(path)
    data["prompt_changes"][0]["source_snapshot_receipt_sha256"] = "f" * 64
    write(path, data)
    with pytest.raises(ValueError, match="empty prompt/configuration"):
        audit_module.audit(windows)


def test_per_action_clock_cannot_hide_a_jump_with_an_unchanged_window_total(windows):
    segment = windows[0][0] / "game/native/segment-0"
    path = segment / "checkpoint/trace.jsonl"
    rows = native_audit.trace(path)
    rows[0]["tick_advance"]["start_tick"] += 1
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(ValueError, match="Per-action"):
        native_audit.verify_trace_clocks(segment, 0, 2)


def test_multiple_saved_segments_and_standalone_continuation(windows, tmp_path):
    attempt, _ = run_fixture(tmp_path / "longer", windows[1][1], "continue", segments=2)
    standalone = audit_module.audit([(attempt, windows[1][1])])
    assert standalone["model_responses"] == 4
    assert standalone["cumulative_returned_tokens"] == 600
    assert [row["next_step"] for row in standalone["windows"][0]["segments"]] == [4, 6]
    assert standalone["windows"][0]["saved_elapsed_ticks"] == 60
    chained = audit_module.audit([windows[0], (attempt, windows[1][1])])
    assert chained["model_responses"] == 6


def test_positive_frame_budget_pause_stays_a_pause(tmp_path):
    original = seed(tmp_path / "seed")
    attempt, _ = run_fixture(tmp_path / "paused", original, "fresh", token_limit=100)
    report = audit_module.audit([(attempt, original)])
    assert report["windows"][0]["native_status"] == "paused"
    assert report["model_responses"] == 1
    assert report["long_term_performance_verified"] is False


@pytest.mark.parametrize(
    "filename", ["request.json", "response.json", "summary.json", "claim.json"]
)
def test_missing_model_receipt_is_not_silently_omitted(windows, filename):
    next((windows[0][0] / "model").glob(f"*/{filename}")).unlink()
    with pytest.raises(ValueError, match="regular file"):
        audit_module.audit(windows)


def test_metadata_changed_during_audit_is_rejected(windows, monkeypatch):
    original = audit_module.export_window

    def changed(*args):
        result = original(*args)
        write(windows[0][0] / "model-admission.json", {"allowed": False})
        return result

    monkeypatch.setattr(audit_module, "export_window", changed)
    with pytest.raises(ValueError, match="changed after"):
        audit_module.audit(windows)


@pytest.mark.parametrize("field", ["vm_teardown_audited", "current_container_state_observed"])
def test_offline_audit_cannot_claim_a_live_observation(windows, tmp_path, field):
    value = audit_module.audit(windows)
    value[field] = True
    path = tmp_path / "audit.json"
    write(path, value)
    with pytest.raises(ValueError, match="cannot claim"):
        recording.export(
            [row[0] for row in windows],
            path,
            recording.sha(path),
            identity="fixture",
            title="Fixture",
        )
