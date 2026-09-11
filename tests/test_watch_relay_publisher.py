"""Process loss is distinct from a transient observation failure."""

from types import SimpleNamespace

import pytest

from scripts import relay_watch as relay


def result(code=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=code, stdout=stdout, stderr=stderr)


def test_process_identity_binds_start_command_and_directory(monkeypatch):
    replies = iter(
        [result(stdout="Fri Sep 11 owner.py run\n"), result(stdout="p7\nfcwd\nn/project/owner\n")]
    )
    monkeypatch.setattr(relay.subprocess, "run", lambda *a, **k: next(replies))
    assert relay.process_identity(7) == {
        "start_and_command": "Fri Sep 11 owner.py run",
        "cwd": "/project/owner",
    }


def test_missing_process_is_terminal(monkeypatch):
    monkeypatch.setattr(relay.subprocess, "run", lambda *a, **k: result(code=1))
    assert relay.process_identity(7) is None


@pytest.mark.parametrize(
    "failure", [result(code=1, stderr="denied"), result(code=0), result(code=2)]
)
def test_observation_failure_is_not_a_missing_owner(monkeypatch, failure):
    monkeypatch.setattr(relay.subprocess, "run", lambda *a, **k: failure)
    with pytest.raises(RuntimeError):
        relay.process_identity(7)


def binding(tmp_path):
    attempt = tmp_path / "owner/attempt"
    attempt.mkdir(parents=True)
    return {
        "schema_version": "fortgym.watch-relay-binding/v1",
        "attempt": str(attempt),
        "owner_pid": 7,
        "owner_identity": {"start_and_command": "start owner", "cwd": str(attempt.parent)},
        "source_checkout": str(tmp_path),
        "source_revision": "a" * 40,
        "run_id": "current",
        "model": "astra",
        "saved_checkpoint_cursor": 256,
        "local_public_directory": str(tmp_path / "public"),
    }


@pytest.mark.parametrize(
    "replacement", [None, {"start_and_command": "reused pid", "cwd": "/different"}]
)
def test_owner_exit_or_pid_reuse_ends_only_the_broadcast(tmp_path, monkeypatch, replacement):
    bound = binding(tmp_path)
    identities = iter([bound["owner_identity"], replacement])
    monkeypatch.setattr(relay, "process_identity", lambda pid: next(identities))
    seen = []

    def snapshot(attempt, base, *, alive, now):
        seen.append(alive)
        return {"frame": None, "owner_alive": alive}

    monkeypatch.setattr(
        relay,
        "load_observer",
        lambda *a: SimpleNamespace(snapshot=snapshot, publish=lambda *a: None),
    )
    monkeypatch.setattr(relay, "send", lambda *a: {"status": "stopped", "decision": None})
    monkeypatch.setattr(relay.time, "sleep", lambda _: pytest.fail("No sleep after owner exit"))
    relay.run(bound, maximum_seconds=10)
    assert seen == [False]


def test_transient_observation_failure_does_not_publish_stopped(tmp_path, monkeypatch):
    bound = binding(tmp_path)
    calls = 0

    def identity(pid):
        nonlocal calls
        calls += 1
        if calls == 1:
            return bound["owner_identity"]
        raise RuntimeError("temporary observation failure")

    monkeypatch.setattr(relay, "process_identity", identity)
    monkeypatch.setattr(
        relay,
        "load_observer",
        lambda *a: SimpleNamespace(
            snapshot=lambda *a, **k: pytest.fail("No terminal claim on read error")
        ),
    )
    times = iter([0, 0, 2])
    monkeypatch.setattr(relay.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(relay.time, "sleep", lambda _: None)
    relay.run(bound, maximum_seconds=1)


def test_ssh_receiver_arguments_are_quoted_and_not_options():
    bound = {
        "remote_root": "/opt/a path; literal",
        "run_id": "run; literal",
        "identity_file": "/private/key",
        "destination": "user@example.com",
    }
    command = relay.ssh_command(bound)
    assert (
        command[-1]
        == "cd '/opt/a path; literal' && python3 -m scripts.receive_watch_relay --run-id 'run; literal'"
    )
    assert "StrictHostKeyChecking=yes" in command
    bound["destination"] = "-oProxyCommand=unexpected"
    with pytest.raises(ValueError):
        relay.ssh_command(bound)


def test_terminal_delivery_failure_is_bounded(tmp_path, monkeypatch, capsys):
    bound = binding(tmp_path)
    identities = iter([bound["owner_identity"], None, None, None])
    monkeypatch.setattr(relay, "process_identity", lambda pid: next(identities))
    monkeypatch.setattr(
        relay,
        "load_observer",
        lambda *a: SimpleNamespace(
            snapshot=lambda *a, **k: {"frame": None, "owner_alive": False},
            publish=lambda *a: None,
        ),
    )
    deliveries = []

    def fail(*args):
        deliveries.append(args)
        raise RuntimeError("SSH unavailable")

    monkeypatch.setattr(relay, "send", fail)
    monkeypatch.setattr(relay.time, "sleep", lambda _: None)
    relay.run(bound, maximum_seconds=100)
    assert len(deliveries) == 3
    assert "owner_stopped_delivery_unavailable" in capsys.readouterr().out


@pytest.mark.parametrize(
    "receipt",
    [
        {"published": True, "run_id": "other", "decision": 9},
        {"published": True, "run_id": "current", "decision": 8},
        {"published": False, "run_id": "current", "decision": 9},
    ],
)
def test_sender_requires_matching_acknowledgement(monkeypatch, receipt):
    import json

    monkeypatch.setattr(relay, "ssh_command", lambda _: ["ssh"])
    monkeypatch.setattr(relay.subprocess, "run", lambda *a, **k: result(stdout=json.dumps(receipt)))
    with pytest.raises(ValueError):
        relay.send({"run_id": "current"}, {"frame": {"decision": 9}})
