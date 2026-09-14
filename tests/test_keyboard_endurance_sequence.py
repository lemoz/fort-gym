import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import campaign_keyboard_endurance_sequence as sequence


@pytest.fixture
def audit_fixture(operation, monkeypatch):
    base, previous, value = operation
    value["origin"] = str(base / "prior-checkpoint")
    put(previous, value)
    attempt = Path(value["owner_output"])
    state = {
        "budget_extensions": [{"limits": sequence.LIMITS}],
        "usage": {"returned_responses": 132, "total_tokens": 3799537},
    }
    agent = attempt / "game/native/segment-0/checkpoint/agent.json"
    put(agent, state)
    out = base / "sequence"
    out.mkdir()
    coordinator = sequence.Coordinator(base, base / "runtime", out)
    report = {
        "passed": True,
        "campaign_id": sequence.CAMPAIGN,
        "source_revision": sequence.SOURCE,
        "image": sequence.IMAGE,
        "cumulative_returned_tokens": 3799537,
        "windows": [
            {
                "first_step": 68,
                "next_step": 132,
                "new_model_responses": 64,
                "segments": [{"segment_index": 0}],
                "checkpoint_manifest_sha256": "a" * 64,
                "saved_elapsed_ticks": 40700,
                "saved_metrics": {"population": 7},
            }
        ],
    }
    calls = []

    def run(command, **kwargs):
        assert kwargs == {"cwd": coordinator.source, "check": True}
        calls.append(command)
        output = Path(command[command.index("--output") + 1])
        put(output, report if "--window" in command else {"frames": []})

    monkeypatch.setattr(sequence.subprocess, "run", run)
    return coordinator, previous, value, report, state, agent, calls


def test_audit_exports_only_the_new_window_and_keeps_delivery_unproven(audit_fixture):
    coordinator, previous, value, _report, _state, _agent, calls = audit_fixture
    result = coordinator.audit(previous, value)
    assert len(calls) == 2 and calls[0].count("--window") == 1
    assert calls[0][2:4] == ["-m", "scripts.campaign_keyboard_docker_audit"]
    assert calls[1][calls[1].index("--id") + 1] == sequence.CAMPAIGN + "-69-132"
    assert result["decision"] == 132 and result["cumulative_returned_tokens"] == 3799537
    assert result["website_recording_published"] is False
    assert result["full_goal_complete"] is False
    assert result["reported_subscription_charge_usd"] is None


@pytest.mark.parametrize(
    "key,value",
    [
        ("passed", False),
        ("campaign_id", "wrong"),
        ("source_revision", "wrong"),
        ("image", "wrong"),
        ("windows", []),
    ],
)
def test_audit_report_mismatch_never_exports_or_launches(audit_fixture, key, value):
    coordinator, previous, operation_value, report, _state, _agent, calls = (
        audit_fixture
    )
    report[key] = value
    with pytest.raises(ValueError):
        coordinator.audit(previous, operation_value)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "key,value",
    [
        ("first_step", 0),
        ("next_step", 131),
        ("new_model_responses", 63),
    ],
)
def test_wrong_saved_boundary_never_exports(audit_fixture, key, value):
    coordinator, previous, operation_value, report, _state, _agent, calls = (
        audit_fixture
    )
    report["windows"][0][key] = value
    with pytest.raises(ValueError):
        coordinator.audit(previous, operation_value)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "change", ["duplicate_extension", "changed_limit", "reset_usage"]
)
def test_budget_reset_or_extension_change_stops_before_export(audit_fixture, change):
    coordinator, previous, value, _report, state, agent, calls = audit_fixture
    if change == "duplicate_extension":
        state["budget_extensions"] *= 2
    elif change == "changed_limit":
        state["budget_extensions"] = [
            {"limits": {"max_dispatches": 1092, "max_total_tokens": 40000000}}
        ]
    else:
        state["usage"]["returned_responses"] = 64
    put(agent, state)
    with pytest.raises(ValueError):
        coordinator.audit(previous, value)
    assert len(calls) == 1


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


@pytest.fixture
def operation(tmp_path):
    base = tmp_path / "operators"
    attempt = tmp_path / (sequence.CAMPAIGN + "-69-132")
    put(attempt / "owner-result.json", {"status": "execution_finished"})
    path = base / "continuation-68-132-operation/result.json"
    value = dict(
        schema_version="fortgym.endurance-continue-operation/v1",
        mode="continue",
        campaign_id=sequence.CAMPAIGN,
        source_revision=sequence.SOURCE,
        image=sequence.IMAGE,
        owner_execution_finished=True,
        running_containers_before_vm_stop="",
        first_step=68,
        window_end_decision=132,
        owner_output=str(attempt),
        owner_result_sha256=sequence.sha(attempt / "owner-result.json"),
        **{key: True for key in sequence.STOP_FLAGS},
    )
    put(path, value)
    return base, path, value


def test_settled_operation_preserves_nonzero_poweroff_and_derives_next_window(
    operation,
):
    base, path, value = operation
    value["guest-poweroff_returncode"] = 1
    put(path, value)
    assert sequence.settled(path, base) == value
    end, attempt, operation_path = sequence.next_paths(value, base)
    assert end == 196 and attempt.name == sequence.CAMPAIGN + "-133-196"
    assert operation_path == base / "continuation-132-196-operation/result.json"


@pytest.mark.parametrize(
    "key,value",
    [
        ("owner_execution_finished", False),
        ("both_vms_stopped", False),
        ("fg-portable_disk_closed", False),
        ("prior_inventory_preserved", False),
        ("configs_unchanged", False),
        ("global_context_unchanged", False),
        ("running_containers_before_vm_stop", "unexpected"),
        ("campaign_id", "other"),
        ("image", "different"),
        ("source_revision", "different"),
        ("window_end_decision", 133),
        ("first_step", 69),
        ("mode", "fresh"),
        ("owner_result_sha256", "0" * 64),
        ("container_audit_error", "failure"),
    ],
)
def test_unsettled_or_changed_operation_never_admits_next_window(operation, key, value):
    base, path, data = operation
    data[key] = value
    put(path, data)
    with pytest.raises(ValueError):
        sequence.settled(path, base)


@pytest.mark.parametrize("end", [4, 67, 131, 1028, 1092, True])
def test_undeclared_or_exhausted_boundary_is_not_extended(tmp_path, end):
    with pytest.raises(ValueError):
        sequence.next_paths({"window_end_decision": end}, tmp_path)


def simulated(monkeypatch, tmp_path, start=132, population=7):
    base = tmp_path / "operators"
    base.mkdir()
    coordinator = sequence.Coordinator(base, tmp_path / "source", base / "sequence")
    coordinator.verify_tools = lambda: None
    values = {}
    events = []
    initial = base / f"prior-{start}.json"
    values[initial] = {"window_end_decision": start}
    monkeypatch.setattr(sequence, "settled", lambda path, _base: values[path])

    def audit(previous, value):
        end = value["window_end_decision"]
        events.append(("audit", end))
        return {"decision": end, "saved_metrics": {"population": population}}

    def run(previous, value):
        end = value["window_end_decision"] + 64
        events.append(("run", end))
        path = base / f"prior-{end}.json"
        values[path] = {"window_end_decision": end}
        coordinator.launched_windows += 1
        return path

    coordinator.audit = audit
    coordinator.run_window = run
    return coordinator, initial, events


def test_audits_before_every_launch_and_after_the_final_window(monkeypatch, tmp_path):
    coordinator, initial, events = simulated(monkeypatch, tmp_path)
    result = coordinator.execute(initial, 2)
    assert events == [
        ("audit", 132),
        ("run", 196),
        ("audit", 196),
        ("run", 260),
        ("audit", 260),
    ]
    assert result["last_verified_decision"] == 260 and result["launched_windows"] == 2
    assert result["status"] == "declared_boundary_reached"
    assert result["full_goal_complete"] is False


def test_stops_at_the_original_response_ceiling_without_extending_it(
    monkeypatch, tmp_path
):
    coordinator, initial, events = simulated(monkeypatch, tmp_path, start=964)
    result = coordinator.execute(initial, 16)
    assert events == [("audit", 964), ("run", 1028), ("audit", 1028)]
    assert result["launched_windows"] == 1


def test_zero_population_stops_but_unknown_population_does_not(monkeypatch, tmp_path):
    coordinator, initial, events = simulated(monkeypatch, tmp_path, population=0)
    result = coordinator.execute(initial, 2)
    assert events == [("audit", 132)] and result["status"] == "no_living_population"


def test_unknown_population_is_not_reclassified_as_collapse(monkeypatch, tmp_path):
    coordinator, initial, events = simulated(monkeypatch, tmp_path, population=None)
    result = coordinator.execute(initial, 1)
    assert result["status"] == "declared_boundary_reached" and ("run", 196) in events


def test_audit_failure_never_launches_or_retries_a_window(monkeypatch, tmp_path):
    coordinator, initial, events = simulated(monkeypatch, tmp_path)
    coordinator.audit = lambda *_args: (_ for _ in ()).throw(
        ValueError("failed native proof")
    )
    result = coordinator.execute(initial, 2)
    assert events == [] and result["launched_windows"] == 0
    assert result["status"] == "stopped_for_inspection"


def test_failed_launched_window_stays_counted_without_retry(monkeypatch, tmp_path):
    coordinator, initial, events = simulated(monkeypatch, tmp_path)

    def failed(*args):
        coordinator.launched_windows += 1
        raise ValueError("operator failed with preserved output")

    coordinator.run_window = failed
    result = coordinator.execute(initial, 2)
    assert result["launched_windows"] == 1 and result["last_verified_decision"] == 132
    assert result["status"] == "stopped_for_inspection" and events == [("audit", 132)]


def test_stop_request_does_not_start_another_window(monkeypatch, tmp_path):
    coordinator, initial, events = simulated(monkeypatch, tmp_path)
    coordinator.request_stop()
    result = coordinator.execute(initial, 2)
    assert events == [("audit", 132)] and result["status"] == "interrupted"


@pytest.mark.parametrize("count", [0, 17, -1, True])
def test_invalid_invocation_window_count_is_rejected_without_output(
    monkeypatch, tmp_path, count
):
    coordinator, initial, _events = simulated(monkeypatch, tmp_path)
    with pytest.raises(ValueError):
        coordinator.execute(initial, count)
    assert not coordinator.output.exists()


def test_stop_signals_only_the_exact_owned_supervisor(tmp_path):
    coordinator = sequence.Coordinator(tmp_path, tmp_path, tmp_path)
    calls = []
    coordinator.child = SimpleNamespace(
        poll=lambda: None, terminate=lambda: calls.append("stop")
    )
    coordinator.request_stop()
    assert calls == ["stop"] and coordinator.stop_requested
    coordinator.child = SimpleNamespace(
        poll=lambda: 0, terminate=lambda: calls.append("wrong")
    )
    coordinator.request_stop()
    assert calls == ["stop"]


def test_relay_start_failure_does_not_interrupt_the_owned_window(monkeypatch, tmp_path):
    base = tmp_path / "ops"
    base.mkdir()
    out = base / "sequence"
    out.mkdir()
    coordinator = sequence.Coordinator(base, tmp_path, out)
    previous = base / "prior.json"
    value = {"window_end_decision": 132, "owner_output": str(tmp_path / "prior")}
    target, attempt, operation = sequence.next_paths(value, base)
    calls = []

    class Owner:
        pid = 100
        returncode = 0
        checks = 0

        def poll(self):
            self.checks += 1
            return None if self.checks == 1 else 0

        def wait(self, **kwargs):
            return 0

        def terminate(self):
            calls.append("terminated")

    owner = Owner()

    def popen(command, **kwargs):
        if command[2].endswith("run_continue.py"):
            put(attempt / "owner-plan.json", {})
            calls.append("owner")
            return owner
        calls.append("relay")
        raise OSError("observer unavailable")

    monkeypatch.setattr(sequence.subprocess, "Popen", popen)
    monkeypatch.setattr(sequence.time, "sleep", lambda _: None)
    assert coordinator.run_window(previous, value) == operation
    assert calls == ["owner", "relay"]
    assert coordinator.launched_windows == 1


def test_log_failure_after_spawn_still_lets_the_supervisor_clean_up(
    monkeypatch, tmp_path
):
    base = tmp_path / "ops"
    base.mkdir()
    out = base / "sequence"
    out.mkdir()
    coordinator = sequence.Coordinator(base, tmp_path, out)
    calls = []
    owner = SimpleNamespace(
        pid=100,
        poll=lambda: None,
        terminate=lambda: calls.append("terminate"),
        wait=lambda: calls.append("wait"),
    )
    monkeypatch.setattr(sequence.subprocess, "Popen", lambda *args, **kwargs: owner)
    coordinator.record = lambda value: (_ for _ in ()).throw(OSError("log full"))
    with pytest.raises(OSError):
        coordinator.run_window(
            base / "prior.json",
            {"window_end_decision": 132, "owner_output": str(tmp_path / "prior")},
        )
    assert calls == ["terminate", "wait"] and coordinator.child is None
