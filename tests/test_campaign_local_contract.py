"""Synthetic contract-probe bookkeeping, with no real inference or game process."""

import json

import pytest

from fort_gym.bench.agent.campaign_local import LocalCampaignAgent
from fort_gym.bench.config import get_settings
from fort_gym.bench.run.campaign_config import load_segment_config
from scripts.campaign_local_contract import probe
from tests.test_campaign_local import CONFIG, ENDPOINT, MODEL, fake_server, policy


@pytest.fixture
def config(monkeypatch):
    monkeypatch.setenv("FORT_GYM_DISABLE_DOTENV", "1")
    get_settings.cache_clear()
    yield load_segment_config(CONFIG, MODEL)
    get_settings.cache_clear()


def test_probe_retains_all_mismatches_as_synthetic_only(config, tmp_path, monkeypatch):
    calls = fake_server(config, monkeypatch)
    result = probe(policy(config, tmp_path), tmp_path)
    assert len(calls) == len(result["cases"]) == 3
    assert result["all_cases_exact"] is False
    assert result["native_actions_executed"] == 0
    assert result["native_game_loaded"] is False
    assert result["usage"]["total_tokens"] == 45
    assert json.loads((tmp_path / "result.json").read_text()) == result


def test_probe_stops_on_unresolved_transport_failure(config, tmp_path, monkeypatch):
    agent = policy(config, tmp_path)

    def fail(messages):
        raise RuntimeError("synthetic transport failure")

    monkeypatch.setattr(agent, "_create_completion", fail)
    result = probe(agent, tmp_path)
    assert len(result["cases"]) == 1
    assert not result["all_cases_exact"]
    assert result["cases"][0]["error_type"] == "RuntimeError"
    assert result["usage"]["dispatched_requests"] == 0


def test_uninitialized_accounting_is_rejected_before_dispatch(config, tmp_path, monkeypatch):
    calls = fake_server(config, monkeypatch)
    agent = LocalCampaignAgent(
        config=config, model=MODEL, endpoint=ENDPOINT, journal=tmp_path / "spend.jsonl"
    )
    with pytest.raises(ValueError, match="Set campaign context"):
        probe(agent, tmp_path)
    assert not calls and not (tmp_path / "spend.jsonl").exists()
