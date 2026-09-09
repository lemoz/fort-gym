"""Prompt-only experiments retain model decisions, checkpoint memory and usage."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import pytest

from fort_gym.bench.agent import keyboard_decision
from fort_gym.bench.agent import codex_transport as transport
from fort_gym.bench.agent.campaign_keyboard import CodexKeyboardAgent
from fort_gym.bench.agent.codex_transport import CodexTransportError
from fort_gym.bench.agent.keyboard_courier import answer_request
from fort_gym.bench.agent.keyboard_exchange import digest, read, validate_request
from fort_gym.bench.agent.keyboard_prompt import (
    BASE_PROMPT, MEMORY_PROMPT, MEMORY_CONTRACT, declared_prompt_change, effective_prompt,
)
from fort_gym.bench.run.campaign_checkpoint import verify_checkpoint
from fort_gym.bench.run.keyboard_config import validate_condition, load_window
from fort_gym.bench.run.keyboard_segment import run_keyboard_segment
from tests.test_campaign_codex_keyboard import decision
from tests.test_keyboard_decision import response
from tests.test_codex_transport import FakeProcess, events
from tests.test_keyboard_runtime import CONDITION, environment, policy, request, saved as saved


def condition(profile=MEMORY_PROMPT):
    return {**CONDITION, "schema_version": "fortgym.codex-keyboard-condition/v3",
            "condition_id": "offline-memory-contract", "prompt_profile": profile}


def selection():
    return {**request(), "schema_version": "fortgym.keyboard-exchange-request/v3",
            "model": "gpt-6-astra", "reasoning_effort": "medium", "prompt_profile": MEMORY_PROMPT}


def declaration(checkpoint):
    manifest = verify_checkpoint(checkpoint)
    return {
        "schema_version": "fortgym.keyboard-prompt-change-declaration/v1",
        "checkpoint_sha256": manifest["sha256"], "next_step": manifest["payload"]["next_step"],
        "previous": BASE_PROMPT, "profile": MEMORY_PROMPT,
    }


def changed_decision(*args):
    return {**decision(*args), "prompt_profile": MEMORY_PROMPT}


@pytest.mark.parametrize("profiles", [{}, {"control_profile": "native_keyboard/v2",
                                         "observation_profile": "native_screen_text/v1"}])
def test_opt_in_changes_only_memory_instruction_and_receipt(tmp_path, monkeypatch, profiles):
    calls, results = [], []

    def transport(prompt, schema, **kwargs):
        calls.append((prompt, schema))
        return {"accepted": True, "response": response(),
                "run_directory": str(kwargs["artifact_root"])}

    monkeypatch.setattr(keyboard_decision, "request_decision", transport)
    for i, options in enumerate(({}, {"prompt_profile": BASE_PROMPT}, {"prompt_profile": MEMORY_PROMPT})):
        output = tmp_path / str(i)
        output.mkdir()
        results.append(keyboard_decision.request_keyboard_decision(
            {"width": 1, "height": 1, "tiles": [[65, 7, 0]]},
            executable=Path(sys.executable), artifact_root=output, allowance_check=lambda: {},
            memory="unchanged model-written memory", **profiles, **options,
        ))
    assert calls[0] == calls[1]
    assert calls[2][0].replace("\n" + MEMORY_CONTRACT + "\n", "") == calls[0][0]
    assert calls[2][1] == calls[0][1]
    assert [r["action"] for r in results] == [response()] * 3
    assert all(r["action"]["memory_update"] == "" for r in results)
    assert "prompt_profile" not in results[0]
    assert results[2]["prompt_profile"] == MEMORY_PROMPT


def test_courier_binds_profile_before_claim_or_model_call(tmp_path):
    calls = []

    def callback(screen, **kwargs):
        calls.append(kwargs)
        return {"transport_receipt": {"dispatched": False}, "prompt_profile": kwargs["prompt_profile"]}

    response_value, _ = answer_request(
        selection(), directory=tmp_path, condition=condition(), executable=Path(sys.executable),
        decision=callback,
    )
    assert calls[0]["prompt_profile"] == MEMORY_PROMPT
    assert response_value["request_sha256"] == digest(selection())
    assert digest(selection()) != digest({**selection(), "prompt_profile": BASE_PROMPT})
    assert read(tmp_path / "response.json") == response_value


def test_real_courier_to_prompt_and_receipt_uses_only_declared_contract(tmp_path, monkeypatch):
    action = decision(selection()["screen"], "", None)["action"]
    raw = "\n".join(json.dumps(event) for event in events(response=action))
    spawned = []

    def spawn(command, **kwargs):
        process = FakeProcess(command, output=raw, **kwargs)
        spawned.append(process)
        return process

    monkeypatch.setattr(transport.subprocess, "Popen", spawn)
    value, summary = answer_request(
        selection(), directory=tmp_path, condition=condition(), executable=Path(sys.executable),
        allowance_check=lambda: {"allowed": True, "basis": "offline_fixture"},
    )
    result = value["result"]
    assert len(spawned) == 1 and summary["total_tokens"] == 110
    assert result["prompt_profile"] == MEMORY_PROMPT and result["action"] == action
    receipt = result["transport_receipt"]
    assert receipt["model_requested"] == "gpt-6-astra"
    assert receipt["reasoning_effort_requested"] == "medium"
    assert receipt["reported_charge_usd"] is None
    retained = read(Path(receipt["run_directory"]) / "request.json")
    prompt = (Path(receipt["run_directory"]) / "prompt.txt").read_text()
    assert MEMORY_CONTRACT in prompt
    assert retained["prompt_sha256"] == hashlib.sha256(prompt.encode()).hexdigest()


@pytest.mark.parametrize("change", [{"prompt_profile": BASE_PROMPT}, {"prompt_profile": "unknown"},
                                     {"schema_version": "fortgym.keyboard-exchange-request/v2"}])
def test_profile_mismatch_never_dispatches_or_claims(tmp_path, change):
    with pytest.raises(ValueError):
        answer_request({**selection(), **change}, directory=tmp_path, condition=condition(),
                       executable=Path(sys.executable),
                       decision=lambda *a, **k: pytest.fail("Mismatched prompt dispatched"))
    assert not list(tmp_path.iterdir())


def test_missing_or_legacy_prompt_identity_rejected():
    value = selection()
    del value["prompt_profile"]
    with pytest.raises(ValueError):
        validate_request(value)
    with pytest.raises(ValueError):
        validate_condition({**CONDITION, "prompt_profile": MEMORY_PROMPT})


def run_segment(output, checkpoint, usage, tick, *, change=None, config=None, callback=changed_decision):
    env = environment()
    env.tick = tick
    agent = policy(CONDITION, callback)
    result = run_keyboard_segment(
        agent=agent, environment=env, snapshotter=env, output=output,
        condition=config or condition(), checkpoint=checkpoint, latest_usage=usage,
        steps=2, expected_cursor=verify_checkpoint(checkpoint)["payload"]["next_step"],
        revision="offline", prompt_change=change,
    )
    return result, env, agent


def test_declared_change_and_next_resume_keep_memory_usage_and_history(tmp_path, saved):
    checkpoint, usage, tick = saved
    before = read(checkpoint / "agent.json")
    output = tmp_path / "changed"
    result, env, agent = run_segment(output, checkpoint, usage, tick, change=declaration(checkpoint))
    assert result["checkpoint_verified"] is True and result["next_step"] == 3
    start = read(output / "agent-before.json")
    assert all(start[k] == before[k] for k in before)
    assert start["prompt_changes"][0]["usage"] == {"dispatched_requests": 1, "total_tokens": 100}
    assert agent.memory == before["memory"] + "xx"
    assert agent.usage["total_tokens"] == 300 and agent.usage["accounted_responses"] == 3
    assert (output / "loop/usage.jsonl").read_bytes().startswith(usage.read_bytes())
    state = agent.export_campaign_state()
    result2, _, agent2 = run_segment(tmp_path / "next", output / "checkpoint",
                                    output / "loop/usage.jsonl", env.tick)
    assert result2["checkpoint_verified"] is True
    assert agent2.prompt_changes == state["prompt_changes"]
    assert agent2.memory == state["memory"] + "xx"
    assert agent2.usage["total_tokens"] == 500
    with pytest.raises(ValueError, match="without a declared change"):
        run_segment(tmp_path / "silent-rollback", output / "checkpoint",
                    output / "loop/usage.jsonl", env.tick, config=CONDITION)
    assert not (tmp_path / "silent-rollback").exists()


@pytest.mark.parametrize("mutation", ["missing", "digest", "cursor", "previous"])
def test_undeclared_or_wrong_boundary_change_never_reads_game(tmp_path, saved, mutation):
    checkpoint, usage, tick = saved
    change = declaration(checkpoint)
    if mutation == "missing":
        change = None
    else:
        change[{"digest": "checkpoint_sha256", "cursor": "next_step", "previous": "previous"}[mutation]] = "invalid"
    with pytest.raises(ValueError):
        run_segment(tmp_path / "bad", checkpoint, usage, tick, change=change,
                    callback=lambda *args: pytest.fail("Invalid prompt reached model"))
    assert not (tmp_path / "bad").exists()


def test_wrong_prompt_receipt_keeps_usage_without_gameplay(tmp_path, saved):
    checkpoint, usage, tick = saved
    result, env, agent = run_segment(tmp_path / "mismatch", checkpoint, usage, tick,
                                    change=declaration(checkpoint), callback=decision)
    assert result["status"] == "checkpoint_failed" or result["stop_reason"] == "unsettled_failure"
    assert result["error_type"] == CodexTransportError.__name__
    assert not env.actions and agent.memory == read(checkpoint / "agent.json")["memory"]
    assert agent.usage["total_tokens"] == 200 and agent.usage["accounted_responses"] == 2


def test_prompt_history_cannot_invent_usage_or_drop_lineage(saved):
    checkpoint, _, _ = saved
    before = read(checkpoint / "agent.json")
    declared = declaration(checkpoint)
    change = declared_prompt_change(before, declared, profile=MEMORY_PROMPT,
                                   checkpoint_sha256=declared["checkpoint_sha256"], next_step=1)
    for mutation in ("usage", "previous", "profile"):
        altered = deepcopy(change)
        if mutation == "usage":
            altered["usage"]["total_tokens"] = 101
        else:
            altered[mutation] = "invalid"
        with pytest.raises(ValueError):
            effective_prompt([altered], before["usage"])
        state = {**before, "prompt_changes": [altered]}
        agent = CodexKeyboardAgent(decision=decision, max_dispatches=8, max_total_tokens=500000)
        with pytest.raises(ValueError):
            agent.restore_campaign_state(state, campaign_id=before["campaign_id"])


def test_declared_native_experiment_keeps_other_condition_fields():
    root = Path(__file__).resolve().parents[1]
    original = json.loads((root / "experiments/campaign_astra_keyboard_20260907.json").read_bytes())
    selected, window = load_window(
        root / "experiments/campaign_astra_keyboard_memory_contract_20260909.json",
        root / "experiments/campaign_astra_keyboard_window_20260909u.json",
    )
    assert all(selected[k] == v for k, v in original.items() if k not in ("condition_id", "schema_version"))
    assert selected["prompt_profile"] == MEMORY_PROMPT
    assert window["continuation_from_next_step"] == 775
    assert window["steps_per_segment"] == 64 and window["max_segments"] == 1
    assert "restart" not in window and "budget_extension" not in window
    assert window["reset_memory"] is window["reset_usage"] is window["strategy_intervention"] is False
