"""Local-transport test doubles. Never contact the actual local model server."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from fort_gym.bench.agent import campaign_local
from fort_gym.bench.agent.campaign_local import COST_BASIS, LocalInferenceError, local_endpoint
from fort_gym.bench.agent.governed_llm import GovernedBudgetCapError
from fort_gym.bench.config import get_settings
from fort_gym.bench.eval.campaign_profile import usage_profile
from fort_gym.bench.run.campaign_config import load_segment_config
from scripts.campaign_development import make_agent
from scripts.campaign_run import budget_reached
from scripts.campaign_segment import run_segment
from tests.test_campaign_loop import TestEnvironment

CONFIG = (
    Path(__file__).resolve().parents[1] / "experiments/campaigns/local_native_development_v1.json"
)
MODEL = "qwen2.5:7b-instruct"
ENDPOINT = "http://127.0.0.1:11439"


@pytest.fixture
def config(monkeypatch):
    monkeypatch.setenv("FORT_GYM_DISABLE_DOTENV", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "must-never-use-this-test-hosted-key")
    get_settings.cache_clear()
    yield load_segment_config(CONFIG, MODEL)
    get_settings.cache_clear()


def policy(config, root):
    agent = make_agent(
        config, MODEL, root / "spend.jsonl", persist_dispatches=True, local_endpoint=ENDPOINT
    )
    agent.set_campaign_context(campaign_id="local-test")
    return agent


def fake_server(config, monkeypatch, mutate=None):
    calls = []

    def request(endpoint, path, *, body=None, timeout=3):
        assert endpoint == ENDPOINT
        if path == "/api/version":
            return {"version": config["local_inference"]["server_version"]}
        if path == "/api/tags":
            return {
                "models": [
                    {"name": MODEL, "digest": config["local_inference"]["model_digests"][MODEL]}
                ]
            }
        assert path == "/api/chat" and body is not None
        calls.append(json.loads(body))
        response = {
            "model": MODEL,
            "done": True,
            "prompt_eval_count": 10,
            "eval_count": 5,
            "message": {
                "content": json.dumps(
                    {
                        "type": "WAIT",
                        "params": {},
                        "advance_ticks": 20,
                        "intent": "synthetic local action",
                    }
                )
            },
        }
        if mutate:
            mutate(response)
        return response

    monkeypatch.setattr(campaign_local, "local_json", request)
    return calls


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://api.openrouter.ai",
        "http://localhost:11439",
        "http://0.0.0.0:11439",
        "http://127.0.0.1:11439@outside.example:80",
        "http://secret@127.0.0.1:11439",
        "http://127.0.0.1:11439/remote",
        "http://127.0.0.1:11439?redirect=outside",
    ],
)
def test_local_route_cannot_name_a_hosted_destination(endpoint):
    with pytest.raises(ValueError):
        local_endpoint(endpoint)


def test_local_transport_cannot_create_a_hosted_client_or_serialize_its_key(config, tmp_path):
    agent = policy(config, tmp_path)
    assert agent._api_key is None
    with pytest.raises(LocalInferenceError, match="hosted client"):
        agent._client_instance()
    with pytest.raises(LocalInferenceError, match="Hosted dispatch"):
        agent._dispatch_completion({})
    assert "must-never-use" not in json.dumps(agent.export_campaign_state())


def test_request_and_checkpoint_use_declared_local_policy_and_usage(config, tmp_path, monkeypatch):
    calls = fake_server(config, monkeypatch)
    agent = policy(config, tmp_path)
    action = agent.decide("Test-only observation", {})
    assert action["type"] == "WAIT" and action["advance_ticks"] == 20
    assert calls[0]["format"]["required"] == ["type", "params", "advance_ticks"]
    assert calls[0]["options"]["num_ctx"] == config["local_inference"]["context_tokens"]
    assert "provider" not in calls[0] and "test-hosted-key" not in json.dumps(calls)
    state = agent.export_campaign_state()
    assert state["usage"] == {
        "total_tokens": 15,
        "total_cost_usd": "0",
        "returned_responses": 1,
        "accounted_responses": 1,
        "dispatched_requests": 1,
        "cost_basis": COST_BASIS,
    }
    reported = usage_profile(state["usage"])
    assert reported["reported_model_cost_usd"] is None
    assert (
        reported["metered_provider_charge_usd"] == "0"
        and reported["infrastructure_cost_usd"] is None
    )
    assert usage_profile(reported)["metered_provider_charge_usd"] == "0"
    assert not budget_reached(state["usage"], config)


def test_local_policy_checkpoint_continuation_retains_memory_and_dispatches(
    config, tmp_path, monkeypatch
):
    calls = fake_server(config, monkeypatch)
    first = tmp_path / "first"
    first.mkdir()
    env = TestEnvironment()
    one = run_segment(
        agent=policy(config, first),
        environment=env,
        snapshotter=env,
        output=first,
        config=config,
        campaign_id="local-test",
        model=MODEL,
        revision="a" * 40,
    )
    checkpoint = Path(one["checkpoint"])
    second = tmp_path / "second"
    second.mkdir()
    env.state = json.loads((checkpoint / "game/world.sav").read_text())
    two = run_segment(
        agent=policy(config, second),
        environment=env,
        snapshotter=env,
        output=second,
        config=config,
        campaign_id="local-test",
        model=MODEL,
        revision="a" * 40,
        checkpoint=checkpoint,
        latest_usage=first / "campaign/usage.jsonl",
    )
    assert one["status"] == two["status"] == "bounded_segment_complete"
    assert two["first_step"] == 3 and two["next_step"] == len(calls) == 6
    assert two["usage"]["total_tokens"] == 90 and two["usage"]["dispatched_requests"] == 6
    assert "Last Action:" in calls[3]["messages"][1]["content"]


def test_local_dispatch_and_context_bounds_stop_before_inference(config, tmp_path, monkeypatch):
    config = {**config, "max_dispatches": 1}
    calls = fake_server(config, monkeypatch)
    agent = policy(config, tmp_path)
    agent.decide("Test observation", {})
    with pytest.raises(GovernedBudgetCapError):
        agent.decide("Test observation again", {})
    assert len(calls) == 1
    fresh = policy(config, tmp_path)
    with pytest.raises(GovernedBudgetCapError, match="context bound"):
        fresh.decide("x" * 25000, {})
    assert fresh.dispatches == 0 and len(calls) == 1


def test_changed_model_identity_fails_before_inference(config, tmp_path, monkeypatch):
    server_config = deepcopy(config)
    server_config["local_inference"]["model_digests"][MODEL] = "0" * 64
    calls = fake_server(server_config, monkeypatch)
    with pytest.raises(LocalInferenceError, match="manifest differs"):
        policy(config, tmp_path).decide("Test-only observation", {})
    assert calls == []


@pytest.mark.parametrize(
    "field,value", [("prompt_eval_count", None), ("eval_count", True), ("eval_count", -1)]
)
def test_missing_or_invalid_local_tokens_are_not_fabricated(
    config, tmp_path, monkeypatch, field, value
):
    fake_server(config, monkeypatch, lambda response: response.update({field: value}))
    agent = policy(config, tmp_path)
    with pytest.raises(LocalInferenceError, match="token telemetry"):
        agent.decide("Test observation", {})
    usage = agent.export_campaign_state()["usage"]
    assert usage["dispatched_requests"] == usage["returned_responses"] == 1
    assert usage["accounted_responses"] == 0


def test_local_http_client_disables_proxies_redirects_and_credential_headers(monkeypatch):
    requests = []
    original = httpx.Client

    def respond(request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": "https://unapproved.example"})

    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return original(**kwargs, transport=httpx.MockTransport(respond))

    monkeypatch.setattr(campaign_local.httpx, "Client", client)
    with pytest.raises(LocalInferenceError, match="transport failed"):
        campaign_local.local_json(ENDPOINT, "/api/chat", body=b"{}")
    assert len(requests) == 1
    assert "authorization" not in requests[0].headers


@pytest.mark.parametrize(
    "key,value", [("max_cost_usd", 1), ("max_cost_usd", False), ("max_attempts", 2)]
)
def test_local_configuration_rejects_undeclared_costs_or_transport_retries(
    tmp_path, config, key, value
):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({**config, key: value}))
    with pytest.raises(ValueError):
        load_segment_config(path, MODEL)


def test_local_checkpoint_rejects_a_fabricated_metered_charge(config, tmp_path):
    state = policy(config, tmp_path).export_campaign_state()
    state["usage"]["total_cost_usd"] = "0.25"
    with pytest.raises(ValueError, match="usage identity"):
        policy(config, tmp_path).restore_campaign_state(state, campaign_id="local-test")


def test_local_configuration_does_not_opt_into_unknown_server_routing(config, tmp_path):
    config["local_inference"]["server_version"] = "99.0.0"
    path = tmp_path / "condition.json"
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="verified pre-cloud"):
        load_segment_config(path, MODEL)


def test_visible_contract_presents_actual_schema_without_changing_it(config, tmp_path, monkeypatch):
    config["local_inference"]["prompt_contract"] = "visible_action_contract/v1"
    calls = fake_server(config, monkeypatch)
    agent = policy(config, tmp_path)
    agent.decide("Test-only observation", {})
    prompt = calls[0]["messages"][-1]["content"]
    visible_schema = json.loads(prompt.split("\n", 1)[1])
    assert visible_schema == calls[0]["format"]
    assert visible_schema["properties"]["advance_ticks"]["minimum"] == 0
    assert visible_schema["properties"]["advance_ticks"]["maximum"] == 2000
    assert "choose the value yourself" in prompt
    assert calls[0]["format"]["required"] == ["type", "params", "advance_ticks"]


def test_legacy_local_condition_keeps_original_message_and_checkpoint_identity(
    config, tmp_path, monkeypatch
):
    calls = fake_server(config, monkeypatch)
    agent = policy(config, tmp_path)
    checkpoint = agent.export_campaign_state()
    agent.decide("Test-only observation", {})
    assert calls[0]["messages"][-1]["content"] == campaign_local.LEGACY_RESPONSE_INSTRUCTION
    changed = deepcopy(config)
    changed["local_inference"]["prompt_contract"] = "visible_action_contract/v1"
    with pytest.raises(ValueError, match="configuration"):
        policy(changed, tmp_path).restore_campaign_state(checkpoint, campaign_id="local-test")


@pytest.mark.parametrize("contract", ["unknown/v1", None, False, [], {}])
def test_unknown_prompt_contract_is_not_silently_used(config, tmp_path, contract):
    config["local_inference"]["prompt_contract"] = contract
    path = tmp_path / "condition.json"
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="prompt contract"):
        load_segment_config(path, MODEL)


def test_visible_contract_condition_preserves_baseline_execution_settings(config):
    variant = load_segment_config(CONFIG.with_name("local_native_visible_contract_v1.json"), MODEL)
    for key in config.keys() - {"condition_id", "hypothesis", "notes", "local_inference"}:
        assert variant[key] == config[key]
    assert variant["local_inference"] == {
        **config["local_inference"],
        "prompt_contract": "visible_action_contract/v1",
    }
