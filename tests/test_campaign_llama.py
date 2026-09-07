"""Local llama.cpp transport doubles: no live model, native game or hosted calls."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from fort_gym.bench.agent import campaign_llama as llama
from fort_gym.bench.agent import campaign_llama_identity as identity
from fort_gym.bench.agent.campaign_local import (
    LocalInferenceError,
    LocalOutputLimitPause,
)
from fort_gym.bench.agent.governed_llm import GovernedBudgetCapError
from fort_gym.bench.run.campaign_config import (
    decision_time_reserve,
    load_segment_config,
    validate_local_settings,
)
from scripts.campaign_development import make_agent, verify_local_transport
from scripts.campaign_local_contract import probe
from scripts.campaign_local_server import server_environment

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "experiments/campaigns/local_native_llama_typed_v1.json"
MODEL = "fort-gym-qwen35-9b-q4-03b74727a860"
ENDPOINT = "http://127.0.0.1:11440"
MESSAGES = [{"role": "user", "content": "Synthetic state, no live game."}]


@pytest.fixture
def config(monkeypatch):
    monkeypatch.setenv("FORT_GYM_DISABLE_DOTENV", "1")
    cfg = load_segment_config(CONFIG, MODEL)
    cfg["local_inference"]["chat_template_sha256"][MODEL] = hashlib.sha256(
        b"test-template"
    ).hexdigest()
    cfg["local_inference"]["model_metadata_sha256"][MODEL] = identity.json_digest(
        {"test_model": True}
    )
    return cfg


def policy(config, tmp_path):
    result = make_agent(
        config, MODEL, tmp_path / "spend.jsonl", persist_dispatches=True, local_endpoint=ENDPOINT
    )
    result.set_campaign_context(campaign_id="llama-test")
    return result


def fake_server(config, monkeypatch, *, input_tokens=42, mutate=None):
    calls = []
    props = {
        "build_info": identity.BUILD,
        "total_slots": 1,
        "is_sleeping": False,
        "default_generation_settings": {"n_ctx": config["local_inference"]["context_tokens"]},
        "model_path": "/synthetic/" + config["local_inference"]["model_files"][MODEL],
        "chat_template": "test-template",
    }

    def request(endpoint, path, *, body=None, timeout=3):
        assert endpoint == ENDPOINT
        calls.append((path, json.loads(body) if body else None))
        if path == "/props":
            return deepcopy(props)
        if path == "/v1/models":
            return {"data": [{"id": MODEL, "meta": {"test_model": True}}]}
        if path == llama.TOKEN_PATH:
            assert timeout == config["local_inference"]["token_count_timeout_seconds"]
            return {"object": "response.input_tokens", "input_tokens": input_tokens}
        assert path == llama.CHAT_PATH and body is not None
        assert timeout == config["local_inference"]["timeout_seconds"]
        response = {
            "model": MODEL,
            "system_fingerprint": identity.BUILD,
            "usage": {
                "prompt_tokens": input_tokens,
                "completion_tokens": 7,
                "total_tokens": input_tokens + 7,
            },
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": '{"type":"WAIT","params":{},"advance_ticks":20}',
                    },
                }
            ],
        }
        if mutate:
            mutate(response, props)
        return response

    monkeypatch.setattr(llama, "local_json", request)
    monkeypatch.setattr(identity, "local_json", request)
    return calls, props


def generations(calls):
    return [body for path, body in calls if path == llama.CHAT_PATH]


def test_native_launcher_preflight_uses_declared_llama_identity(config, monkeypatch):
    calls, _ = fake_server(config, monkeypatch)
    verify_local_transport(ENDPOINT, config, MODEL)
    assert [path for path, _ in calls] == ["/props", "/v1/models"]


def test_unknown_transport_cannot_fall_back_to_ollama(config, tmp_path):
    config["local_inference"]["transport"] = "unknown/v1"
    with pytest.raises(ValueError, match="Unsupported local campaign transport"):
        policy(config, tmp_path)
    with pytest.raises(ValueError, match="Unsupported local campaign transport"):
        verify_local_transport(ENDPOINT, config, MODEL)


@pytest.mark.parametrize("value", [None, 0, 1, "false", [], {}])
def test_thinking_mode_requires_a_real_boolean(config, value):
    config["local_inference"]["enable_thinking"] = value
    with pytest.raises(ValueError, match="explicit boolean"):
        validate_local_settings(config, MODEL)


def test_thinking_mode_is_exactly_requested_counted_and_checkpoint_bound(
    config, tmp_path, monkeypatch
):
    calls, _ = fake_server(config, monkeypatch)
    original = policy(config, tmp_path)
    original._create_completion(MESSAGES)
    saved = original.export_campaign_state()
    thinking = deepcopy(config)
    thinking["local_inference"]["enable_thinking"] = True
    agent = make_agent(
        thinking,
        MODEL,
        tmp_path / "thinking.jsonl",
        persist_dispatches=True,
        local_endpoint=ENDPOINT,
    )
    with pytest.raises(ValueError):
        agent.restore_campaign_state(saved, campaign_id="llama-test")
    agent.set_campaign_context(campaign_id="thinking-test")
    agent._create_completion(MESSAGES)
    body = generations(calls)[-1]
    assert body["chat_template_kwargs"] == {"enable_thinking": True}
    assert [body for path, body in calls if path == llama.TOKEN_PATH][-1] == body
    assert agent.export_campaign_state()["usage"]["total_tokens"] == 49


def test_factory_routes_pinned_local_transport_and_retains_real_usage(
    config, tmp_path, monkeypatch
):
    calls, _ = fake_server(config, monkeypatch)
    agent = policy(config, tmp_path)
    assert isinstance(agent, llama.LlamaCampaignAgent)
    response = agent._create_completion(MESSAGES)
    assert response["usage"]["total_tokens"] == 49
    generation = generations(calls)[0]
    assert "reasoning_budget_tokens" not in generation
    counts = [body for path, body in calls if path == llama.TOKEN_PATH]
    assert counts == [generation]
    assert generation["chat_template_kwargs"] == {"enable_thinking": False}
    assert generation["response_format"]["schema"] == agent._action_tool()["function"]["parameters"]
    assert agent.export_campaign_state()["usage"] == {
        "total_tokens": 49,
        "total_cost_usd": "0",
        "returned_responses": 1,
        "accounted_responses": 1,
        "dispatched_requests": 1,
        "cost_basis": "self_hosted_no_metered_provider",
    }
    event = agent.pop_tool_events()[0]
    assert event["tool"] == "campaign_llama.chat"
    assert event["input"]["prompt_tokens"] == 42
    assert event["output"]["usage"] == response["usage"]
    assert (
        event["input"]["identity"]["scope"]
        == "observed_api_properties_not_a_weight_file_hash_attestation"
    )
    assert [
        json.loads(line)["type"] for line in (tmp_path / "spend.jsonl").read_text().splitlines()
    ] == ["dispatch_started", "dispatch_finished_or_failed"]


def test_payload_bytes_are_not_treated_as_context_tokens(config, tmp_path, monkeypatch):
    calls, _ = fake_server(config, monkeypatch)
    agent = policy(config, tmp_path)
    messages = [{"role": "user", "content": "x" * 34000}]
    body = agent._serialize_request(messages)
    assert 32768 < len(body) < 65536
    agent._create_completion(messages)
    assert len(generations(calls)) == 1


def test_byte_limit_stops_before_any_control_or_generation_request(config, tmp_path, monkeypatch):
    config["max_request_bytes"] = 1
    calls, _ = fake_server(config, monkeypatch)
    agent = policy(config, tmp_path)
    with pytest.raises(GovernedBudgetCapError, match="byte bound"):
        agent._create_completion(MESSAGES)
    assert calls == [] and agent.dispatches == 0


@pytest.mark.parametrize("count", [31233, 32768, 99999])
def test_measured_context_includes_output_and_headroom(config, tmp_path, monkeypatch, count):
    calls, _ = fake_server(config, monkeypatch, input_tokens=count)
    agent = policy(config, tmp_path)
    with pytest.raises(GovernedBudgetCapError, match="local context"):
        agent._create_completion(MESSAGES)
    assert not generations(calls) and agent.dispatches == 0


def test_cumulative_allowance_reserves_prompt_plus_maximum_output(config, tmp_path, monkeypatch):
    config["max_total_tokens"] = 42 + 1024 - 1
    calls, _ = fake_server(config, monkeypatch)
    agent = policy(config, tmp_path)
    with pytest.raises(GovernedBudgetCapError, match="cumulative tokens"):
        agent._create_completion(MESSAGES)
    assert not generations(calls) and agent.dispatches == 0


@pytest.mark.parametrize("count", [True, None, "42", -1, 0])
def test_invalid_measured_count_cannot_dispatch(config, tmp_path, monkeypatch, count):
    calls, _ = fake_server(config, monkeypatch, input_tokens=count)
    with pytest.raises(LocalInferenceError, match="token count"):
        policy(config, tmp_path)._create_completion(MESSAGES)
    assert not generations(calls)


@pytest.mark.parametrize(
    "field,value", [("total_tokens", 999), ("prompt_tokens", True), ("completion_tokens", None)]
)
def test_bad_returned_usage_keeps_raw_response_and_unaccounted_count(
    config, tmp_path, monkeypatch, field, value
):
    calls, _ = fake_server(
        config, monkeypatch, mutate=lambda response, props: response["usage"].update({field: value})
    )
    agent = policy(config, tmp_path)
    with pytest.raises(LocalInferenceError, match="invalid token usage"):
        agent._create_completion(MESSAGES)
    assert len(generations(calls)) == 1
    usage = agent.export_campaign_state()["usage"]
    assert (
        usage["dispatched_requests"],
        usage["returned_responses"],
        usage["accounted_responses"],
    ) == (1, 1, 0)
    assert agent.pop_tool_events()[0]["output"]["usage"][field] == value


@pytest.mark.parametrize("failure", ["model", "fingerprint", "finish", "context", "prompt_count"])
def test_post_response_failure_still_accounts_returned_usage(
    config, tmp_path, monkeypatch, failure
):
    def mutate(response, props):
        if failure == "model":
            response["model"] = "other-model"
        if failure == "fingerprint":
            response["system_fingerprint"] = "other-build"
        if failure == "finish":
            response["choices"][0]["finish_reason"] = "length"
        if failure == "context":
            props["default_generation_settings"]["n_ctx"] = 4096
        if failure == "prompt_count":
            response["usage"].update(prompt_tokens=43, total_tokens=50)

    calls, _ = fake_server(config, monkeypatch, mutate=mutate)
    agent = policy(config, tmp_path)
    with pytest.raises(LocalInferenceError):
        agent._create_completion(MESSAGES)
    assert len(generations(calls)) == 1
    assert agent.export_campaign_state()["usage"]["accounted_responses"] == 1
    assert len(agent.pop_tool_events()) == 1


def test_actual_preflight_refreshes_cached_identity_before_dispatch(config, tmp_path, monkeypatch):
    calls, props = fake_server(config, monkeypatch)
    agent = policy(config, tmp_path)
    assert agent._body_fits(agent._serialize_request(MESSAGES))
    props["chat_template"] = "changed"
    with pytest.raises(LocalInferenceError, match="template differs"):
        agent._create_completion(MESSAGES)
    assert not generations(calls)


@pytest.mark.parametrize(
    "content", ["", '{"type":', '{"type":"WAIT","params":{},"advance_ticks":20}']
)
def test_output_limit_is_accounted_but_never_returns_a_partial_action(
    config, tmp_path, monkeypatch, content
):
    def mutate(response, props):
        response["usage"].update(
            completion_tokens=config["max_output_tokens"],
            total_tokens=42 + config["max_output_tokens"],
        )
        response["choices"][0]["finish_reason"] = "length"
        response["choices"][0]["message"].update(
            content=content, reasoning_content="PRIVATE-REASONING"
        )

    calls, _ = fake_server(config, monkeypatch, mutate=mutate)
    agent = policy(config, tmp_path)
    with pytest.raises(LocalOutputLimitPause):
        agent._create_completion(MESSAGES)
    assert len(generations(calls)) == 1
    assert (
        agent.export_campaign_state()["usage"]["total_tokens"] == 42 + config["max_output_tokens"]
    )
    assert agent.export_campaign_state()["usage"]["accounted_responses"] == 1
    assert agent.pop_tool_events()[0]["output"]["choices"][0]["message"]["content"] == content
    journal = [json.loads(line) for line in (tmp_path / "spend.jsonl").read_text().splitlines()]
    assert journal[-1]["type"] == "dispatch_finished_or_failed"
    assert journal[-1]["usage"]["dispatched_requests"] == 1


@pytest.mark.parametrize(
    "fault", ["usage", "model", "prompt", "template", "role", "content", "tools", "short_length"]
)
def test_output_length_cannot_bypass_response_verification(config, tmp_path, monkeypatch, fault):
    def mutate(response, props):
        response["choices"][0]["finish_reason"] = "length"
        response["usage"].update(
            completion_tokens=config["max_output_tokens"],
            total_tokens=42 + config["max_output_tokens"],
        )
        message = response["choices"][0]["message"]
        if fault == "usage":
            response["usage"]["total_tokens"] = None
        elif fault == "model":
            response["model"] = "different-model"
        elif fault == "prompt":
            response["usage"]["prompt_tokens"] += 1
            response["usage"]["total_tokens"] += 1
        elif fault == "template":
            props["chat_template"] = "changed"
        elif fault == "role":
            message["role"] = "tool"
        elif fault == "content":
            message["content"] = None
        elif fault == "tools":
            message["tool_calls"] = [{"type": "function"}]
        elif fault == "short_length":
            response["usage"].update(completion_tokens=7, total_tokens=49)

    calls, _ = fake_server(config, monkeypatch, mutate=mutate)
    agent = policy(config, tmp_path)
    with pytest.raises(LocalInferenceError) as error:
        agent._create_completion(MESSAGES)
    assert not isinstance(error.value, LocalOutputLimitPause)
    assert len(generations(calls)) == 1


def test_real_adapter_state_round_trips_after_output_pause_without_native_replay(
    config, tmp_path, monkeypatch
):
    from fort_gym.bench.run.campaign_loop import CampaignLoop, CampaignNoActionPause
    from tests.test_campaign_loop import TestEnvironment

    def mutate(response, props):
        response["choices"][0]["finish_reason"] = "length"
        response["choices"][0]["message"]["content"] = ""
        response["usage"].update(
            completion_tokens=config["max_output_tokens"],
            total_tokens=42 + config["max_output_tokens"],
        )

    calls, _ = fake_server(config, monkeypatch, mutate=mutate)
    agent, environment = policy(config, tmp_path), TestEnvironment()
    loop = CampaignLoop(
        campaign_id="llama-test",
        agent=agent,
        environment=environment,
        output=tmp_path / "loop",
        observation_profile=config["observation_profile"],
        advance_policy=config["advance_policy"],
    )
    with pytest.raises(CampaignNoActionPause):
        loop.step()
    checkpoint = tmp_path / "checkpoint"
    loop.checkpoint(checkpoint, snapshotter=environment, code_revision="test-only")
    saved = agent.export_campaign_state()
    assert len(generations(calls)) == 1 and not environment.actions
    restored_agent = policy(config, tmp_path / "resumed-model")
    resumed = CampaignLoop.resume(
        checkpoint,
        agent=restored_agent,
        environment=TestEnvironment(),
        output=tmp_path / "resumed-loop",
        latest_usage_path=loop.journal,
    )
    assert restored_agent.export_campaign_state() == saved
    assert resumed.next_step == 0 and resumed.committed_elapsed_ticks == 0
    assert len(generations(calls)) == 1 and not resumed.environment.actions


@pytest.mark.parametrize(
    "messages",
    [
        [{"role": [], "content": "x"}],
        [{"role": "user", "content": []}],
        [{"role": "tool", "content": "x"}],
        [{"role": "user", "content": "x", "tools": []}],
    ],
)
def test_only_plain_text_inputs_are_allowed(config, tmp_path, monkeypatch, messages):
    calls, _ = fake_server(config, monkeypatch)
    with pytest.raises(LocalInferenceError, match="plain text"):
        policy(config, tmp_path)._create_completion(messages)
    assert calls == []


def test_probe_uses_new_transport_without_counting_control_calls_as_generation(
    config, tmp_path, monkeypatch
):
    calls, _ = fake_server(config, monkeypatch)
    result = probe(policy(config, tmp_path), tmp_path)
    assert len(generations(calls)) == 3
    assert result["usage"]["accounted_responses"] == 3
    assert result["usage"]["total_tokens"] == 147
    assert result["native_actions_executed"] == 0


def test_checkpoint_round_trip_keeps_transport_and_cumulative_usage(config, tmp_path, monkeypatch):
    fake_server(config, monkeypatch)
    original = policy(config, tmp_path)
    original._create_completion(MESSAGES)
    state = original.export_campaign_state()
    assert state["configuration"]["transport"] == identity.TRANSPORT
    restored = policy(config, tmp_path)
    restored.restore_campaign_state(state, campaign_id="llama-test")
    assert restored.export_campaign_state() == state
    changed = deepcopy(config)
    changed["local_inference"]["context_headroom_tokens"] += 1
    with pytest.raises(ValueError):
        policy(changed, tmp_path).restore_campaign_state(state, campaign_id="llama-test")


def test_declared_profile_has_scheduling_allowance_and_no_ollama_launcher(config, tmp_path):
    assert decision_time_reserve(config) == 1104 < config["segment_time_budget_seconds"]
    with pytest.raises(ValueError, match="Ollama conditions"):
        server_environment(config, cache=tmp_path, port=11440, inherited={})


def test_declared_slow_timeout_reaches_transport_and_cannot_resume_old_state(
    config, tmp_path, monkeypatch
):
    config["checkpoint_policy"] = {
        "profile": "periodic_checkpoints/v1",
        "interval_steps": 8,
        "minimum_free_bytes": 1073741824,
    }
    config["segment_time_budget_seconds"] = 7200
    calls, _ = fake_server(config, monkeypatch)
    old = policy(config, tmp_path)
    state = old.export_campaign_state()
    config["local_inference"]["timeout_seconds"] = 600
    current = policy(config, tmp_path)
    with pytest.raises(ValueError):
        current.restore_campaign_state(state, campaign_id="llama-test")
    current._create_completion(MESSAGES)
    assert len(generations(calls)) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("enable_thinking", "true"),
        ("top_k", True),
        ("top_p", 0),
        ("token_count_timeout_seconds", 0),
        ("context_headroom_tokens", 0),
        ("token_count_profile", "other"),
        ("server_version", "other"),
        ("model_files", {MODEL: "../model.gguf"}),
        ("model_metadata_sha256", {MODEL: "bad"}),
    ],
)
def test_invalid_llama_conditions_fail_before_runtime(config, field, value):
    config["local_inference"][field] = value
    with pytest.raises(ValueError):
        validate_local_settings(config, MODEL)
