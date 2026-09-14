"""Exercise v5 through the real courier and prompt builder, without a provider."""

import json
from pathlib import Path
import sys

import pytest

from fort_gym.bench.agent import codex_transport as transport
from fort_gym.bench.agent.keyboard_courier import answer_request
from fort_gym.bench.agent.keyboard_exchange import digest, read
from fort_gym.bench.env.workshop_job_profile import PROMPT_PROFILE
from tests.test_codex_transport import FakeProcess, events
from tests.test_selected_workshop_profile import condition, job_action, selected_request


@pytest.mark.parametrize("memory", ["", "Retained campaign memory"])
@pytest.mark.parametrize("route", ["KEYSTROKE", "WORKSHOP_JOB"])
def test_v5_real_courier_forwards_prompt_and_retains_either_route(
    tmp_path, monkeypatch, memory, route,
):
    request = {**selected_request(), "memory": memory}
    action = job_action()
    if route == "KEYSTROKE":
        action = {**action, "type": route, "params": {"keys": ["q"]}}
    raw = "\n".join(json.dumps(event) for event in events(response=action))
    spawned = []

    def spawn(command, **kwargs):
        process = FakeProcess(command, output=raw, **kwargs)
        spawned.append(process)
        return process

    monkeypatch.setattr(transport.subprocess, "Popen", spawn)
    response, summary = answer_request(
        request, directory=tmp_path, condition=condition(),
        executable=Path(sys.executable),
        allowance_check=lambda: {"allowed": True, "basis": "offline_fixture"},
    )
    assert len(spawned) == 1
    assert summary["model_dispatched"] is True
    assert summary["action_grammar_valid"] is True
    assert summary["total_tokens"] == 110
    assert summary["reported_charge_usd"] is None
    result = response["result"]
    assert response["request_sha256"] == digest(request)
    assert result["prompt_profile"] == PROMPT_PROFILE
    assert result["action"] == action
    assert result["native_action_dispatched"] is False
    receipt = result["transport_receipt"]
    assert receipt["model_requested"] == request["model"]
    assert receipt["reasoning_effort_requested"] == request["reasoning_effort"]
    run = Path(receipt["run_directory"])
    prompt = (run / "prompt.txt").read_text()
    assert "No workshop is found or selected for you" in prompt
    assert "Return one KEYSTROKE or WORKSHOP_JOB response" in prompt
    assert "Your retained memory:\n" + memory + "\n" in prompt
    assert read(run / "keyboard-decision.json") == result
    assert read(tmp_path / "response.json") == response
    with pytest.raises(FileExistsError):
        answer_request(
            request, directory=tmp_path, condition=condition(),
            executable=Path(sys.executable),
            decision=lambda *args, **kwargs: pytest.fail("Repeated request dispatched"),
        )
    assert len(spawned) == 1
