from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.campaign_development import load_config, make_agent
from fort_gym.bench.agent.governed_llm import DFHackGovernedLLMAgent, GovernedBudgetCapError
from fort_gym.bench.config import get_settings

CONFIG = Path(__file__).resolve().parents[1] / "experiments/campaigns/development_probe_v1.json"


@pytest.fixture
def agent_config(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-only-key-not-a-real-credential")
    monkeypatch.setenv("FORT_GYM_DISABLE_DOTENV", "1")
    get_settings.cache_clear()
    yield load_config(CONFIG, "z-ai/glm-5.3-flash")
    get_settings.cache_clear()


@pytest.mark.parametrize(
    "model", ["z-ai/glm-5.3-flash", "qwen/qwen3.8-flash", "deepseek/deepseek-v4-flash-0731"]
)
def test_declared_models_selected_without_new_agent_classes(tmp_path, agent_config, model):
    agent = make_agent(agent_config, model, tmp_path / "usage.jsonl")
    assert agent._model == model
    assert agent._memory_path is None


def test_unknown_model_not_silently_routed():
    with pytest.raises(ValueError, match="not declared"):
        load_config(CONFIG, "anthropic/unknown")


def test_each_dispatch_gets_price_ceiling_and_durable_usage_journal(
    tmp_path, agent_config, monkeypatch
):
    calls = []
    monkeypatch.setattr(
        DFHackGovernedLLMAgent, "_dispatch_completion", lambda self, request: calls.append(request)
    )
    journal = tmp_path / "spend.jsonl"
    agent = make_agent(agent_config, agent_config["models"][0], journal)
    original = {"messages": [], "extra_body": {"provider": {"order": ["test-provider"]}}}
    agent._dispatch_completion(original)
    assert calls[0]["extra_body"]["provider"]["max_price"] == agent_config["provider_max_price"]
    assert calls[0]["extra_body"]["provider"]["order"] == ["test-provider"]
    assert "max_price" not in original["extra_body"]["provider"]
    events = [json.loads(line) for line in journal.read_text().splitlines()]
    assert [event["type"] for event in events] == [
        "dispatch_started",
        "dispatch_finished_or_failed",
    ]
    assert events[-1]["usage"]["total_cost_usd"] == 0
    assert "test-only-key" not in journal.read_text()


def test_dispatch_bound_stops_all_retry_routes(tmp_path, agent_config, monkeypatch):
    calls = []
    monkeypatch.setattr(
        DFHackGovernedLLMAgent, "_dispatch_completion", lambda self, request: calls.append(request)
    )
    agent = make_agent(agent_config, agent_config["models"][0], tmp_path / "spend.jsonl")
    for _ in range(agent_config["max_dispatches"]):
        agent._dispatch_completion({"messages": []})
    with pytest.raises(GovernedBudgetCapError):
        agent._dispatch_completion({"messages": []})
    assert len(calls) == agent_config["max_dispatches"]


def test_oversized_request_stops_before_dispatch(tmp_path, agent_config, monkeypatch):
    calls = []
    monkeypatch.setattr(
        DFHackGovernedLLMAgent, "_dispatch_completion", lambda self, request: calls.append(request)
    )
    agent = make_agent(agent_config, agent_config["models"][0], tmp_path / "spend.jsonl")
    with pytest.raises(GovernedBudgetCapError):
        agent._dispatch_completion({"messages": ["x" * agent_config["max_request_bytes"]]})
    assert calls == [] and agent.dispatches == 0


def test_transport_failure_is_not_recorded_as_a_charge(tmp_path, agent_config, monkeypatch):
    def fail(self, request):
        raise OSError("test transport unavailable")

    monkeypatch.setattr(DFHackGovernedLLMAgent, "_dispatch_completion", fail)
    journal = tmp_path / "spend.jsonl"
    agent = make_agent(agent_config, agent_config["models"][0], journal)
    with pytest.raises(OSError):
        agent._dispatch_completion({"messages": []})
    events = [json.loads(line) for line in journal.read_text().splitlines()]
    assert events[-1]["usage"]["returned_responses"] == 0
    assert agent.dispatches == 1


def test_worker_initializes_campaign_and_retains_agent_state(tmp_path, agent_config, monkeypatch):
    from scripts.campaign_development import worker
    from fort_gym.bench.run import campaign_save, runner

    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setenv("DFROOT", str(runtime))
    state = {"save_name": "campaign-resume", "paused": True, "year": 30, "year_tick": 19309}
    monkeypatch.setattr(campaign_save, "native_save_status", lambda: state)
    monkeypatch.setattr(
        campaign_save.NativeSaveSnapshotter, "capture", lambda self, path: {"test_double": True}
    )
    contexts = []

    def run(agent, **kwargs):
        contexts.append((agent._campaign_id, kwargs))
        return kwargs["run_id"]

    monkeypatch.setattr(runner, "run_once", run)
    worker(SimpleNamespace(output=tmp_path, model=agent_config["models"][0]), agent_config)
    assert contexts[0][0] == tmp_path.name
    assert contexts[0][1]["preserve_save"] is True
    assert contexts[0][1]["evaluation_protocol"] is None
    result = json.loads((tmp_path / "experiment.json").read_text())
    assert result["status"] == "returned" and result["dispatches"] == 0
    assert json.loads((tmp_path / "agent-final.json").read_text())["campaign_id"] == tmp_path.name
