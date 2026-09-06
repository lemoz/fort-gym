"""Control-reference and identity tests; no model, RPC, or game calls."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from fort_gym.bench.agent import campaign_action_reference as reference
from fort_gym.bench.agent.campaign_llm import CAMPAIGN_SYSTEM_PROMPT
from fort_gym.bench.agent.campaign_local import LocalCampaignAgent
from fort_gym.bench.agent.governed_llm import GovernedBudgetCapError
from fort_gym.bench.run.campaign_config import load_segment_config
from tests.test_campaign_context import observation, extract

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "experiments/campaigns/local_native_qwen14_q3_flash_q8_v1.json"
MODEL = "qwen2.5:14b-instruct-q3_K_M"


def agent(tmp_path, *, with_reference=False, packing=None):
    config = load_segment_config(CONFIG, MODEL)
    if with_reference:
        config["local_inference"]["action_reference"] = "native_designations/v1"
    if packing is not None:
        config["local_inference"]["prompt_packing"] = packing
    result = LocalCampaignAgent(
        config=config,
        model=MODEL,
        endpoint="http://127.0.0.1:11439",
        journal=tmp_path / "unused.jsonl",
    )
    result.set_campaign_context(campaign_id="reference-test")
    return result


@pytest.mark.parametrize("packing", ["none", "bounded_history_corrections/v1"])
def test_reference_is_system_visible_without_changing_current_facts(tmp_path, packing):
    old = agent(tmp_path, packing=packing)
    new = agent(tmp_path, with_reference=True, packing=packing)
    obs = observation()
    before = deepcopy(obs)
    old_messages = old._campaign_messages("Exact current observation", obs)
    messages = new._campaign_messages("Exact current observation", obs)
    assert old_messages[0]["content"] == CAMPAIGN_SYSTEM_PROMPT
    assert messages[0]["content"] == CAMPAIGN_SYSTEM_PROMPT + "\n" + reference.NATIVE_DESIGNATIONS
    assert obs == before
    if packing == "none":
        assert messages[1:] == old_messages[1:]
    else:
        current = extract(messages)
        for key in obs.keys() - {"action_history"}:
            assert current[key] == obs[key]
    assert new._action_tool() == old._action_tool()
    assert new.dispatches == old.dispatches == 0
    assert not (tmp_path / "unused.jsonl").exists()


def test_reference_binds_actual_prompt_bytes_and_cannot_resume_old_identity(tmp_path):
    old = agent(tmp_path)
    new = agent(tmp_path, with_reference=True)
    old_state = old.export_campaign_state()
    new_state = new.export_campaign_state()
    assert (
        old_state["configuration"]["prompt_sha256"]
        == hashlib.sha256(CAMPAIGN_SYSTEM_PROMPT.encode()).hexdigest()
    )
    assert (
        new_state["configuration"]["prompt_sha256"]
        == hashlib.sha256(new._campaign_system_prompt().encode()).hexdigest()
    )
    with pytest.raises(ValueError):
        new.restore_campaign_state(old_state, campaign_id="reference-test")


def test_reference_text_change_is_detected_even_with_same_profile_name(tmp_path, monkeypatch):
    initial = agent(tmp_path, with_reference=True).export_campaign_state()
    monkeypatch.setattr(
        reference, "NATIVE_DESIGNATIONS", reference.NATIVE_DESIGNATIONS + " changed"
    )
    with pytest.raises(ValueError):
        agent(tmp_path, with_reference=True).restore_campaign_state(
            initial, campaign_id="reference-test"
        )


def test_reference_does_not_select_or_rewrite_gameplay(tmp_path):
    old, new = agent(tmp_path), agent(tmp_path, with_reference=True)
    payload = {
        "type": "DIG",
        "params": {"area": [12, 34, 56], "size": [2, 3, 1]},
        "advance_ticks": 37,
    }
    assert new._campaign_action(payload) == old._campaign_action(payload)
    assert new._campaign_action(payload)["params"]["kind"] == "dig"
    for kind in ("dig", "channel", "chop", "gather"):
        selected = {**payload, "params": {**payload["params"], "kind": kind}}
        assert new._campaign_action(selected) == old._campaign_action(selected)


def test_reference_bytes_participate_in_unchanged_request_limit(tmp_path):
    new = agent(tmp_path, with_reference=True)
    messages = new._campaign_messages("Exact current observation", observation())
    body = new._request_body(messages)
    assert reference.NATIVE_DESIGNATIONS in json.loads(body)["messages"][0]["content"]
    new.config["max_request_bytes"] = len(body) - 1
    with pytest.raises(GovernedBudgetCapError, match="context bound"):
        new._request_body(messages)
    assert new.dispatches == 0


@pytest.mark.parametrize("value", [False, None, [], {}, "unknown"])
def test_invalid_reference_rejected_before_dispatch(tmp_path, value):
    config = json.loads(CONFIG.read_text())
    config["local_inference"]["action_reference"] = value
    path = tmp_path / "condition.json"
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="action reference"):
        load_segment_config(path, MODEL)


def test_reference_requires_visible_action_contract(tmp_path):
    config = json.loads(CONFIG.read_text())
    config["local_inference"].update(
        action_reference="native_designations/v1",
        prompt_contract="grammar_only/v1",
    )
    path = tmp_path / "condition.json"
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="visible action contract"):
        load_segment_config(path, MODEL)


@pytest.mark.parametrize(
    "model",
    [
        "qwen2.5:7b-instruct",
        "llama3.1:8b-instruct-q4_K_M",
        "mistral:7b-instruct-v0.3-q4_K_M",
        MODEL,
    ],
)
def test_declared_reference_condition_preserves_execution_bounds_for_every_model(model):
    original = load_segment_config(CONFIG, MODEL)
    config = load_segment_config(
        CONFIG.parent / "local_native_designation_reference_v1.json", model
    )
    for key in original.keys() - {
        "condition_id",
        "hypothesis",
        "models",
        "notes",
        "local_inference",
    }:
        assert config[key] == original[key]
    for key in original["local_inference"].keys() - {"model_digests"}:
        assert config["local_inference"][key] == original["local_inference"][key]
    assert (
        config["local_inference"]["model_digests"][MODEL]
        == original["local_inference"]["model_digests"][MODEL]
    )
    assert config["local_inference"]["action_reference"] == "native_designations/v1"
