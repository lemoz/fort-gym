import json
import subprocess

import pytest

from fort_gym.bench.agent.keyboard_observation import observe_container_output

COMMAND = ["docker", "exec", "owned", "ls"]
INSPECT = ["docker", "inspect", "owned"]
STOPPED = {"Status": "exited", "Running": False, "Restarting": False, "Pid": 0, "ExitCode": 0}


def observe(results, warnings):
    calls = []
    def output(command):
        calls.append(command)
        value = results[len(calls) - 1]
        if isinstance(value, Exception):
            raise value
        return value
    return output, calls


def test_successful_observation_does_not_inspect_or_retry():
    warnings = []
    output, calls = observe(["request-id"], warnings)
    assert observe_container_output(COMMAND, output=output, inspect_command=INSPECT,
                                    retain_warning=warnings.append) == "request-id"
    assert calls == [COMMAND] and warnings == []


@pytest.mark.parametrize("error", [
    RuntimeError("read failed"), subprocess.CalledProcessError(137, COMMAND),
    subprocess.TimeoutExpired(COMMAND, 20),
])
def test_terminal_error_is_retained_without_retry_or_completion_claim(error):
    warnings = []
    output, calls = observe([error, json.dumps(STOPPED)], warnings)
    assert observe_container_output(COMMAND, output=output, inspect_command=INSPECT,
                                    retain_warning=warnings.append) is None
    assert calls == [COMMAND, INSPECT]
    assert len(warnings) == 1 and warnings[0]["error_type"] == type(error).__name__
    assert warnings[0]["terminal_container_state"] == STOPPED
    assert warnings[0]["underlying_cause"] == "unverified"
    assert warnings[0]["native_completion"] == "requires_separate_result_and_checkpoint_audit"


@pytest.mark.parametrize("state", [
    {**STOPPED, "Running": True}, {**STOPPED, "Status": "running"},
    {**STOPPED, "Pid": 9}, {**STOPPED, "Pid": False},
    {**STOPPED, "Restarting": True}, {"Running": False}, None, [],
])
def test_unknown_or_live_state_never_becomes_terminal(state):
    error = subprocess.CalledProcessError(137, COMMAND)
    warnings = []
    output, calls = observe([error, json.dumps(state)], warnings)
    with pytest.raises(subprocess.CalledProcessError) as caught:
        observe_container_output(COMMAND, output=output, inspect_command=INSPECT,
                                 retain_warning=warnings.append)
    assert caught.value is error and warnings == []
    assert calls == [COMMAND, INSPECT]


@pytest.mark.parametrize("state", ["not-json", RuntimeError("inspection unavailable")])
def test_failed_state_recheck_preserves_original_observation_error(state):
    error = subprocess.TimeoutExpired(COMMAND, 20)
    output, calls = observe([error, state], [])
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        observe_container_output(COMMAND, output=output, inspect_command=INSPECT,
                                 retain_warning=lambda value: pytest.fail("No terminal evidence"))
    assert caught.value is error and calls == [COMMAND, INSPECT]


def test_warning_retention_failure_cannot_be_silently_ignored():
    output, _ = observe([RuntimeError("read"), json.dumps(STOPPED)], [])
    def retain(value):
        raise OSError("disk full")
    with pytest.raises(OSError, match="disk full"):
        observe_container_output(COMMAND, output=output, inspect_command=INSPECT, retain_warning=retain)

