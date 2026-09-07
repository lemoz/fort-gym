"""Declared llama.cpp reasoning budgets; no model or game is run by these tests."""

import hashlib
import json
from copy import deepcopy

import pytest

from fort_gym.bench.agent import campaign_llama as llama
from fort_gym.bench.agent.campaign_llama_identity import json_digest
from fort_gym.bench.run.campaign_config import load_segment_config, validate_local_settings
from tests.test_campaign_llama import (
    CONFIG,
    MESSAGES,
    MODEL,
    fake_server,
    generations,
    policy,
)


@pytest.fixture
def config(monkeypatch):
    monkeypatch.setenv("FORT_GYM_DISABLE_DOTENV", "1")
    value = load_segment_config(CONFIG, MODEL)
    value["local_inference"]["chat_template_sha256"][MODEL] = hashlib.sha256(
        b"test-template"
    ).hexdigest()
    value["local_inference"]["model_metadata_sha256"][MODEL] = json_digest({"test_model": True})
    return value


@pytest.mark.parametrize("budget", [None, True, False, -1, 1.5, "2048", 2048, 4096])
def test_reasoning_budget_requires_integer_below_total_output(config, budget):
    config["max_output_tokens"] = 2048
    config["local_inference"].update(enable_thinking=True, reasoning_budget_tokens=budget)
    with pytest.raises(ValueError, match="space for action"):
        validate_local_settings(config, MODEL)


def test_reasoning_budget_cannot_be_silently_ignored_without_thinking(config):
    config["local_inference"]["reasoning_budget_tokens"] = 128
    with pytest.raises(ValueError, match="requires thinking"):
        validate_local_settings(config, MODEL)


def test_reasoning_budget_cannot_be_silently_ignored_by_ollama(config):
    config["local_inference"].update(
        transport="ollama-local/v1", enable_thinking=True, reasoning_budget_tokens=128
    )
    with pytest.raises(ValueError, match="pinned llama.cpp transport"):
        validate_local_settings(config, MODEL)


@pytest.mark.parametrize("budget", [0, 128, 2047])
def test_only_declared_budget_changes_request_and_binds_checkpoint(
    config, tmp_path, monkeypatch, budget
):
    config["max_output_tokens"] = 2048
    config["local_inference"]["enable_thinking"] = True
    calls, _ = fake_server(config, monkeypatch)
    previous = policy(config, tmp_path)
    old_body = json.loads(previous._serialize_request(MESSAGES))
    checkpoint = previous.export_campaign_state()

    changed = deepcopy(config)
    changed["local_inference"]["reasoning_budget_tokens"] = budget
    candidate = policy(changed, tmp_path)
    assert json.loads(candidate._serialize_request(MESSAGES)) == {
        **old_body,
        "reasoning_budget_tokens": budget,
    }
    with pytest.raises(ValueError):
        candidate.restore_campaign_state(checkpoint, campaign_id="llama-test")

    candidate._create_completion(MESSAGES)
    body = generations(calls)[0]
    assert body["reasoning_budget_tokens"] == budget
    assert body["max_tokens"] == 2048
    assert [value for path, value in calls if path == llama.TOKEN_PATH] == [body]
    assert candidate.export_campaign_state()["usage"]["total_tokens"] == 49
