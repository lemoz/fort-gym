"""Synthetic retained messages and transport doubles, no native game or model."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from scripts import campaign_output_replay as replay
from tests.test_campaign_llama import ENDPOINT, MESSAGES
from tests.test_campaign_llama import config as config
from tests.test_campaign_llama import fake_server, policy

PLAN = (
    Path(__file__).resolve().parents[1]
    / "experiments/diagnostics/local_llama_output_budget_v1.json"
)


@pytest.fixture
def inputs(config, tmp_path):
    base = tmp_path / "base.json"
    base.write_text(json.dumps(config))
    plan = json.loads(PLAN.read_text())
    plan.update(
        baseline_condition_file_sha256=replay.digest(base.read_bytes()),
        source_prompt_tokens=42,
        output_token_allowances=[config["max_output_tokens"], config["max_output_tokens"] * 2],
    )
    agent = policy(config, tmp_path)
    body = agent._serialize_request(MESSAGES)
    source = [
        {
            "step": 42,
            "events": [
                {
                    "tool": "campaign_llama.chat",
                    "input": {
                        "messages": deepcopy(MESSAGES),
                        "request_sha256": replay.digest(body),
                    },
                    "output": {
                        "model": agent._model,
                        "usage": {
                            "prompt_tokens": 42,
                            "completion_tokens": config["max_output_tokens"],
                            "total_tokens": 42 + config["max_output_tokens"],
                        },
                        "choices": [
                            {
                                "finish_reason": "length",
                                "message": {"role": "assistant", "content": ""},
                            }
                        ],
                    },
                }
            ],
        }
    ]
    source_path = tmp_path / "source.jsonl"
    source_path.write_text(json.dumps(source[0]) + "\n")
    plan["source_failure_file_sha256"] = replay.digest(source_path.read_bytes())
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan))
    return plan_path, base, source_path


def run(inputs, tmp_path):
    return replay.replay(*inputs, endpoint=ENDPOINT, output=tmp_path / "output", revision="a" * 40)


def test_exact_replay_changes_only_output_limit_and_never_executes_a_game(
    inputs, config, tmp_path, monkeypatch
):
    count = 0

    def mutate(response, props):
        nonlocal count
        count += 1
        if count == 1:
            response["usage"].update(
                completion_tokens=config["max_output_tokens"],
                total_tokens=42 + config["max_output_tokens"],
            )
            response["choices"][0]["finish_reason"] = "length"
            response["choices"][0]["message"].update(
                content="", reasoning_content="PRIVATE-REASONING"
            )

    calls, _ = fake_server(config, monkeypatch, mutate=mutate)
    result = run(inputs, tmp_path)
    assert result["status"] == "two_cases_completed"
    assert [case["status"] for case in result["cases"]] == ["output_limit", "action_returned"]
    assert result["cases"][1]["action_type"] == "WAIT"
    assert result["dispatched_requests"] == result["accounted_responses"] == 2
    assert result["usage_complete"] is True
    assert result["total_tokens"] == 42 + config["max_output_tokens"] + 49
    assert result["native_actions_executed"] == 0 and result["native_game_loaded"] is False
    assert result["native_legality"] == "not_checked"
    requests = [body for path, body in calls if path == "/v1/chat/completions"]
    assert len(requests) == 2 and requests[0]["max_tokens"] * 2 == requests[1]["max_tokens"]
    assert {**requests[1], "max_tokens": requests[0]["max_tokens"]} == requests[0]
    assert "PRIVATE-REASONING" not in json.dumps(result)
    private = tmp_path / f"output/output-{config['max_output_tokens']}/private-response.json"
    assert "PRIVATE-REASONING" in private.read_text()


@pytest.mark.parametrize(
    "fault",
    [
        "source_hash",
        "baseline_hash",
        "source_cursor",
        "request_hash",
        "extra_case",
        "allowance",
        "token_cap",
    ],
)
def test_bad_inputs_cannot_dispatch_or_run_a_different_prompt(
    inputs, config, tmp_path, monkeypatch, fault
):
    plan_path, base_path, source_path = inputs
    plan, source = json.loads(plan_path.read_text()), json.loads(source_path.read_text())
    if fault == "source_hash":
        plan["source_failure_file_sha256"] = "0" * 64
    elif fault == "baseline_hash":
        plan["baseline_condition_file_sha256"] = "0" * 64
    elif fault in {"source_cursor", "request_hash"}:
        if fault == "source_cursor":
            source["step"] += 1
        else:
            source["events"][0]["input"]["request_sha256"] = "0" * 64
        source_path.write_text(json.dumps(source) + "\n")
        plan["source_failure_file_sha256"] = replay.digest(source_path.read_bytes())
    elif fault == "extra_case":
        plan["output_token_allowances"].append(4096)
    elif fault == "allowance":
        plan["output_token_allowances"][1] = True
    elif fault == "token_cap":
        plan["max_total_tokens"] = 10
    plan_path.write_text(json.dumps(plan))
    calls, _ = fake_server(config, monkeypatch)
    with pytest.raises(ValueError):
        run(inputs, tmp_path)
    assert calls == []


@pytest.mark.parametrize("fault", ["usage", "identity", "content", "timeout"])
def test_failed_response_ends_diagnostic_without_a_retry(
    inputs, config, tmp_path, monkeypatch, fault
):
    def mutate(response, props):
        if fault == "usage":
            response["usage"]["total_tokens"] = None
        elif fault == "identity":
            response["model"] = "wrong-model"
        elif fault == "content":
            response["choices"][0]["message"]["content"] = "not an action"
        else:
            raise TimeoutError("synthetic timeout")

    calls, _ = fake_server(config, monkeypatch, mutate=mutate)
    result = run(inputs, tmp_path)
    assert result["status"] == "stopped_without_retry"
    assert len(result["cases"]) == 1 and result["cases"][0]["status"] == "failed"
    assert len([path for path, _ in calls if path == "/v1/chat/completions"]) == 1
    assert result["dispatched_requests"] == 1
    assert result["usage_complete"] is (fault not in {"usage", "timeout"})


def test_non_loopback_endpoint_is_rejected_before_any_request(
    inputs, config, tmp_path, monkeypatch
):
    calls, _ = fake_server(config, monkeypatch)
    with pytest.raises(ValueError, match="loopback"):
        replay.replay(
            *inputs, endpoint="https://example.com", output=tmp_path / "output", revision="a" * 40
        )
    assert calls == []


def test_missing_authorized_source_prevents_all_network_calls(
    inputs, config, tmp_path, monkeypatch
):
    calls, _ = fake_server(config, monkeypatch)
    with pytest.raises(ValueError, match="regular local files"):
        replay.replay(
            *inputs[:2],
            tmp_path / "missing.jsonl",
            endpoint=ENDPOINT,
            output=tmp_path / "output",
            revision="a" * 40,
        )
    assert calls == [] and not (tmp_path / "output").exists()
