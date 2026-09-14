import json
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from fort_gym.bench.agent import codex_transport as transport
from fort_gym.bench.agent.codex_protocol import CODE_MODE_DISABLED, decode_events


def events(*, diagnostic=False, response=None):
    result = [{"type": "thread.started", "thread_id": "synthetic"}]
    if diagnostic:
        result.append(
            {"type": "item.completed", "item": {"type": "error", "message": CODE_MODE_DISABLED}}
        )
    result.extend(
        [
            {"type": "turn.started"},
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": json.dumps(response or {"ok": True})},
            },
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 100,
                    "cached_input_tokens": 20,
                    "output_tokens": 10,
                    "reasoning_output_tokens": 2,
                },
            },
        ]
    )
    return result


def decode(values, **kwargs):
    return decode_events("\n".join(json.dumps(event) for event in values), exit_code=0, **kwargs)


def test_valid_structured_response_retains_usage_without_inventing_cost():
    receipt = decode(events())
    assert receipt["accepted"] is True
    assert receipt["response"] == {"ok": True}
    assert receipt["total_tokens"] == 110
    assert receipt["reported_charge_usd"] is None
    assert receipt["native_game_commands"] == 0


def test_exact_pre_turn_disabled_host_diagnostic_is_not_a_tool_call():
    receipt = decode(events(diagnostic=True))
    assert receipt["accepted"] is True
    assert receipt["diagnostics"] == [CODE_MODE_DISABLED]


@pytest.mark.parametrize(
    "kind",
    ["command_execution", "mcp_tool_call", "file_change", "web_search", "future_unknown_tool"],
)
def test_unexpected_tool_activity_rejects_but_keeps_usage(kind):
    values = events()
    values.insert(2, {"type": "item.started", "item": {"type": kind}})
    receipt = decode(values)
    assert receipt["accepted"] is False
    assert "unexpected_codex_item" in receipt["errors"]
    assert receipt["total_tokens"] == 110


@pytest.mark.parametrize("message", ["Provider failed", "", CODE_MODE_DISABLED + " other error"])
def test_other_diagnostics_are_not_silenced(message):
    values = events(diagnostic=True)
    values[1]["item"]["message"] = message
    assert decode(values)["accepted"] is False


def test_disabled_host_error_after_start_is_not_ignored():
    values = events(diagnostic=True)
    values[1], values[2] = values[2], values[1]
    assert decode(values)["accepted"] is False


@pytest.mark.parametrize(
    "usage",
    [
        None,
        {},
        {"input_tokens": True, "output_tokens": 1, "cached_input_tokens": 0},
        {"input_tokens": 5, "output_tokens": 1, "cached_input_tokens": 6},
        {"input_tokens": 5, "output_tokens": -1, "cached_input_tokens": 0},
    ],
)
def test_missing_or_invalid_usage_rejects(usage):
    values = events()
    values[-1]["usage"] = usage
    receipt = decode(values)
    assert not receipt["accepted"]
    assert receipt["usage"] == [usage]
    assert not receipt["usage_complete"]


@pytest.mark.parametrize("text", ["not JSON", "[]", "null", "```json\n{}\n```", '{"value":NaN}'])
def test_bad_final_does_not_lose_usage_or_synthesize_action(text):
    values = events()
    values[2]["item"]["text"] = text
    receipt = decode(values)
    assert not receipt["accepted"]
    assert receipt["response"] is None
    assert receipt["total_tokens"] == 110


def test_failure_after_success_and_duplicate_turns_are_rejected():
    values = events()
    values.append({"type": "turn.failed", "error": {"message": "failed"}})
    assert not decode(values)["accepted"]
    assert not decode(events() + events())["accepted"]


def test_malformed_event_is_retained_as_failure():
    raw = "not json\n" + "\n".join(json.dumps(event) for event in events())
    receipt = decode_events(raw, exit_code=0)
    assert "invalid_event_json" in receipt["errors"]
    assert receipt["total_tokens"] == 110


def test_exit_and_timeout_reject_even_with_final_response():
    raw = "\n".join(json.dumps(event) for event in events())
    assert not decode_events(raw, exit_code=1)["accepted"]
    receipt = decode_events(raw, exit_code=-15, timed_out=True)
    assert "codex_timeout" in receipt["errors"]
    assert receipt["total_tokens"] == 110


def test_command_pins_requested_model_and_no_tool_subscription_route(tmp_path):
    command = transport.invocation(Path(sys.executable), tmp_path / "schema.json")
    assert command[command.index("--model") + 1] == "gpt-6-astra"
    assert 'model_reasoning_effort="medium"' in command
    assert 'forced_login_method="chatgpt"' in command
    assert "--ignore-user-config" in command
    assert "--ephemeral" in command
    assert command[-1] == "-"
    assert "--dangerously-bypass-approvals-and-sandbox" not in command
    assert "shell_tool" in command and "code_mode_host" in command


def test_environment_does_not_inherit_secrets_or_provider_overrides():
    source = {
        "HOME": "/test/home",
        "PATH": "/usr/bin",
        "OPENAI_API_KEY": "private",
        "CODEX_API_KEY": "private",
        "CODEX_HOME": "/other/account",
        "HTTPS_PROXY": "http://proxy",
        "OPENAI_BASE_URL": "http://provider",
    }
    assert transport.isolated_environment(source) == {"HOME": "/test/home", "PATH": "/usr/bin"}


class FakeProcess:
    def __init__(self, command, *, output, timeout=False, **kwargs):
        self.command, self.kwargs, self.returncode = command, kwargs, None
        self.pid, self.timeout, self.input, self.waits = 99999, timeout, None, []
        kwargs["stdout"].write(output.encode())

    def communicate(self, *, input, timeout):
        self.input = input
        if self.timeout:
            raise subprocess.TimeoutExpired(self.command, timeout)
        self.returncode = 0

    def poll(self):
        return self.returncode

    def wait(self, *, timeout):
        self.waits.append(timeout)
        self.returncode = -15


def invoke(tmp_path, monkeypatch, *, timeout=False, output=None, allowance=None):
    calls = []
    raw = (
        output
        if output is not None
        else "\n".join(json.dumps(event) for event in events(diagnostic=True))
    )

    def spawn(command, **kwargs):
        process = FakeProcess(command, output=raw, timeout=timeout, **kwargs)
        calls.append(process)
        return process

    monkeypatch.setattr(transport.subprocess, "Popen", spawn)
    receipt = transport.request_decision(
        'Synthetic observation only: return {"ok":true}. $(not-a-shell-command)',
        {"type": "object"},
        executable=Path(sys.executable),
        artifact_root=tmp_path,
        allowance_check=allowance or (lambda: {"allowed": True, "basis": "offline_fixture"}),
    )
    return receipt, calls


def test_request_retains_exact_prompt_schema_events_and_receipt(tmp_path, monkeypatch):
    receipt, calls = invoke(tmp_path, monkeypatch)
    assert receipt["accepted"] and receipt["dispatched"]
    assert len(calls) == 1
    process = calls[0]
    assert b"$(not-a-shell-command)" in process.input
    assert all("not-a-shell-command" not in arg for arg in process.command)
    assert process.kwargs["start_new_session"] is True
    directory = Path(receipt["run_directory"])
    assert json.loads((directory / "result.json").read_text()) == receipt
    assert (directory / "prompt.txt").read_bytes() == process.input
    request_record = json.loads((directory / "request.json").read_text())
    assert request_record["dispatch_outcome"] == "unknown_until_result_receipt"
    assert "dispatched" not in request_record
    assert {"events.jsonl", "stderr.log", "request.json", "output-schema.json"} <= {
        path.name for path in directory.iterdir()
    }


def test_allowance_denial_precedes_process_and_artifact_creation(tmp_path, monkeypatch):
    with pytest.raises(transport.CodexTransportError) as caught:
        invoke(tmp_path, monkeypatch, allowance=lambda: {"allowed": False, "basis": "exhausted"})
    assert caught.value.receipt["dispatched"] is False
    assert not list(tmp_path.iterdir())


def test_timeout_terminates_only_owned_group_and_preserves_receipt(tmp_path, monkeypatch):
    kills = []
    monkeypatch.setattr(transport.os, "killpg", lambda pid, sig: kills.append((pid, sig)))
    with pytest.raises(transport.CodexTransportError) as caught:
        invoke(tmp_path, monkeypatch, timeout=True)
    assert kills == [(99999, signal.SIGTERM)]
    assert caught.value.receipt["timed_out"]
    assert caught.value.receipt["total_tokens"] == 110
    assert Path(caught.value.receipt["run_directory"], "result.json").exists()


def test_bad_response_is_not_retried(tmp_path, monkeypatch):
    with pytest.raises(transport.CodexTransportError) as caught:
        invoke(tmp_path, monkeypatch, output="broken JSON")
    assert len(list(tmp_path.iterdir())) == 1
    assert not caught.value.receipt["accepted"]


def test_launch_failure_retains_a_nondispatch_receipt(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("synthetic launch failure")

    monkeypatch.setattr(transport.subprocess, "Popen", fail)
    with pytest.raises(transport.CodexTransportError) as caught:
        transport.request_decision(
            "Synthetic",
            {"type": "object"},
            executable=Path(sys.executable),
            artifact_root=tmp_path,
            allowance_check=lambda: {"allowed": True, "basis": "offline_fixture"},
        )
    assert caught.value.receipt["dispatched"] is False
    assert caught.value.receipt["launch_error"] == "OSError"
    assert caught.value.receipt["usage_complete"] is False


def test_turn_completion_before_start_is_rejected():
    values = events()
    values[1], values[-1] = values[-1], values[1]
    assert "invalid_turn_order" in decode(values)["errors"]
