import hashlib
import json
import subprocess

import pytest

from fort_gym.bench.agent.keyboard_observation import observe_container_output

INSPECT = [
    "docker",
    "--host",
    "owned.sock",
    "inspect",
    "owned",
    "--format",
    "{{json .State}}",
]
LIST = INSPECT[:-4] + [
    "exec",
    "owned",
    "/bin/sh",
    "-c",
    "if test -d /evidence/astra/exchange; then ls -1 /evidence/astra/exchange; fi",
]
LIVE = {
    "Status": "running",
    "Running": True,
    "Restarting": False,
    "Paused": False,
    "OOMKilled": False,
    "Pid": 123,
}
STOPPED = {**LIVE, "Status": "exited", "Running": False, "Pid": 0}


def run(values, *, command=LIST, limit=3, recorder=None):
    calls, failures, warnings, waits = [], [], [], []

    def output(request):
        calls.append(request)
        value = values[len(calls) - 1]
        if isinstance(value, BaseException):
            raise value
        return value

    def execute():
        return observe_container_output(
            command,
            output=output,
            inspect_command=INSPECT,
            retain_warning=warnings.append,
            max_live_read_attempts=limit,
            retain_failure=recorder or failures.append,
            wait=waits.append,
        )

    return execute, calls, failures, warnings, waits


def test_live_read_retries_only_after_retaining_fresh_state_and_output():
    raw = b"temporary runtime read failure" * 500
    error = subprocess.CalledProcessError(128, LIST, output=raw)
    execute, calls, failures, warnings, waits = run(
        [error, json.dumps(LIVE), "request-id"]
    )
    assert execute() == "request-id"
    assert calls == [LIST, INSPECT, LIST] and waits == [0.5] and warnings == []
    assert len(failures) == 1
    failure = failures[0]
    assert failure["container_state"] == LIVE and failure["command_exit_code"] == 128
    assert failure["output_sha256"] == hashlib.sha256(raw).hexdigest()
    assert failure["output_bytes"] == len(raw) and failure["output_truncated"] is True
    assert failure["output_excerpt"] == raw[:8192].decode()
    assert failure["model_or_gameplay_input_retried"] is False


def test_exact_request_readiness_probe_is_supported():
    command = [
        *LIST[:-1],
        "if test -f /evidence/astra/exchange/"
        + "a" * 32
        + "/request.json; then echo ready; fi",
    ]
    execute, calls, *_ = run(["ready"], command=command)
    assert execute() == "ready" and calls == [command]


def test_read_bound_does_not_retry_forever_or_return_fake_empty():
    errors = [subprocess.CalledProcessError(128, LIST, output=str(n)) for n in range(3)]
    sequence = [item for error in errors for item in (error, json.dumps(LIVE))]
    execute, calls, failures, warnings, waits = run(sequence)
    with pytest.raises(subprocess.CalledProcessError) as caught:
        execute()
    assert caught.value is errors[-1]
    assert calls == [LIST, INSPECT] * 3 and waits == [0.5, 1.0]
    assert [x["attempt"] for x in failures] == [1, 2, 3] and warnings == []


@pytest.mark.parametrize(
    "state",
    [
        {**LIVE, "Paused": True},
        {**LIVE, "OOMKilled": True},
        {**LIVE, "Pid": False},
        {**LIVE, "Restarting": True},
        {"Running": True},
        None,
        [],
    ],
)
def test_unknown_live_or_unhealthy_state_is_recorded_but_not_retried(state):
    error = subprocess.CalledProcessError(128, LIST)
    execute, calls, failures, warnings, waits = run([error, json.dumps(state)])
    with pytest.raises(subprocess.CalledProcessError):
        execute()
    assert calls == [LIST, INSPECT] and waits == [] and warnings == []
    assert len(failures) == 1 and failures[0]["output_bytes"] is None


def test_container_exit_during_read_is_still_not_completion():
    execute, calls, failures, warnings, waits = run(
        [RuntimeError("read"), json.dumps(STOPPED)]
    )
    assert execute() is None and calls == [LIST, INSPECT] and waits == []
    assert len(failures) == len(warnings) == 1
    assert (
        warnings[0]["native_completion"]
        == "requires_separate_result_and_checkpoint_audit"
    )


def test_failed_state_inspection_retains_read_failure_without_retry():
    error = subprocess.TimeoutExpired(LIST, 20, output=b"partial")
    execute, calls, failures, _, waits = run([error, "bad-json"])
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        execute()
    assert caught.value is error and waits == [] and calls == [LIST, INSPECT]
    assert failures[0]["inspection_error_type"] == "JSONDecodeError"


@pytest.mark.parametrize(
    "command",
    [
        [*LIST[:-1], "rm -f /evidence/astra/exchange/request.json"],
        [*LIST[:-1], LIST[-1] + "; echo extra"],
        [*LIST[:-4], "other-owner", "/bin/sh", "-c", LIST[-1]],
        [
            "docker",
            "exec",
            "owned",
            "python",
            "-m",
            "scripts.campaign_keyboard_native",
            "publish-response",
        ],
    ],
)
def test_mutations_unknown_commands_and_other_owners_cannot_opt_into_retry(command):
    execute, calls, *_ = run([], command=command)
    with pytest.raises(ValueError, match="exact read-only"):
        execute()
    assert calls == []


@pytest.mark.parametrize("limit", [True, 0, 4, 1.5])
def test_invalid_attempt_bound_never_dispatches(limit):
    execute, calls, *_ = run([], limit=limit)
    with pytest.raises(ValueError, match="finite"):
        execute()
    assert calls == []


def test_failure_recording_failure_never_becomes_a_retry():
    def record(value):
        raise OSError("disk full")

    execute, calls, _, _, waits = run(
        [RuntimeError("read"), json.dumps(LIVE)], recorder=record
    )
    with pytest.raises(OSError, match="disk full"):
        execute()
    assert calls == [LIST, INSPECT] and waits == []
