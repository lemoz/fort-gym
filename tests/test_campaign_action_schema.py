"""Versioned grammar tests only: no model request or native game."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from fort_gym.bench.agent.campaign_action_schema import LEGACY, TYPED, action_tool
from fort_gym.bench.agent.campaign_llm import CampaignLLMAgent
from fort_gym.bench.agent.campaign_local import LocalCampaignAgent
from fort_gym.bench.run.campaign_config import load_segment_config, validate_local_settings

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "experiments/campaigns/local_native_designation_reference_v1.json"
MODEL = "qwen2.5:14b-instruct-q3_K_M"


def agent(tmp_path, profile=None):
    config = load_segment_config(CONFIG, MODEL)
    if profile is not None:
        config["local_inference"]["action_schema"] = profile
    validate_local_settings(config, MODEL)
    result = LocalCampaignAgent(
        config=config,
        model=MODEL,
        endpoint="http://127.0.0.1:11439",
        journal=tmp_path / "unused.jsonl",
    )
    result.set_campaign_context(campaign_id="schema-test")
    return result


def branches(tool):
    return {
        branch["properties"]["type"]["enum"][0]: branch
        for branch in tool["function"]["parameters"]["oneOf"]
    }


def test_legacy_schema_and_identity_remain_unchanged(tmp_path):
    old = agent(tmp_path)
    expected = CampaignLLMAgent._action_tool(old)
    assert old._action_tool() == expected
    assert action_tool(expected, LEGACY) == expected
    assert (
        "action_schema"
        not in old.export_campaign_state()["configuration"]["local_condition"]["local_inference"]
    )
    assert (
        old.export_campaign_state()["configuration"]["action_tool_sha256"]
        == hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest()
    )
    assert old.dispatches == 0 and not (tmp_path / "unused.jsonl").exists()


def test_typed_schema_covers_same_actions_notes_and_runtime_tick_limit(tmp_path):
    old, new = agent(tmp_path), agent(tmp_path, TYPED)
    original = old._action_tool()["function"]["parameters"]
    typed = branches(new._action_tool())
    assert set(typed) == set(original["properties"]["type"]["enum"])
    for kind, schema in typed.items():
        assert schema["required"] == ["type", "params", "advance_ticks"]
        assert schema["additionalProperties"] is False
        assert schema["properties"]["advance_ticks"]["maximum"] == (
            0 if kind == "INTERACT" else 2000
        )
        for key in ("intent", "objective", "plan_step", "memory_update"):
            assert schema["properties"][key] == original["properties"][key]
    assert typed["WAIT"]["properties"]["params"]["properties"] == {}
    assert typed["LABOR"]["properties"]["params"]["properties"]["enable"] == {"type": "boolean"}


@pytest.mark.parametrize("kind", ["DIG", "UNSUSPEND"])
def test_rectangles_require_three_integer_coordinates(tmp_path, kind):
    params = branches(agent(tmp_path, TYPED)._action_tool())[kind]["properties"]["params"]
    for name in ("area", "size"):
        assert params["properties"][name] == {
            "type": "array",
            "items": {"type": "integer"},
            "minItems": 3,
            "maxItems": 3,
        }
        assert name in params["required"]


@pytest.mark.parametrize("mode", ["dig", "channel", "chop", "gather"])
def test_typed_designation_mode_is_explicit_without_rewriting_it(tmp_path, mode):
    new = agent(tmp_path, TYPED)
    params = branches(new._action_tool())["DIG"]["properties"]["params"]
    assert "kind" in params["required"] and mode in params["properties"]["kind"]["enum"]
    payload = {
        "type": "DIG",
        "params": {"area": [1, 2, 3], "size": [2, 3, 1], "kind": mode},
        "advance_ticks": 37,
    }
    assert new._campaign_action(payload) == agent(tmp_path)._campaign_action(payload)
    assert new._campaign_action(payload)["params"]["kind"] == mode


def test_schema_is_in_actual_request_and_checkpoint_identity(tmp_path):
    old, new = agent(tmp_path), agent(tmp_path, TYPED)
    body = json.loads(new._serialize_request([{"role": "user", "content": "synthetic"}]))
    schema = new._action_tool()["function"]["parameters"]
    assert hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest() == (
        "bb627b6a772969459d08e92cd7b2ee61e254e72a2c95746c631cee89c3214e66"
    )
    assert body["format"] == schema
    assert json.dumps(schema, sort_keys=True) in body["messages"][-1]["content"]
    assert old._campaign_system_prompt() == new._campaign_system_prompt()
    assert (
        old.export_campaign_state()["configuration"]["action_tool_sha256"]
        != new.export_campaign_state()["configuration"]["action_tool_sha256"]
    )
    with pytest.raises(ValueError):
        new.restore_campaign_state(old.export_campaign_state(), campaign_id="schema-test")
    with pytest.raises(ValueError):
        old.restore_campaign_state(new.export_campaign_state(), campaign_id="schema-test")


def test_schema_returns_independent_objects(tmp_path):
    legacy = agent(tmp_path)._action_tool()
    before = deepcopy(legacy)
    typed = action_tool(legacy, TYPED)
    branches(typed)["DIG"]["properties"]["params"]["properties"]["area"]["minItems"] = 1
    assert legacy == before
    assert (
        branches(action_tool(legacy, TYPED))["DIG"]["properties"]["params"]["properties"]["area"][
            "minItems"
        ]
        == 3
    )


@pytest.mark.parametrize("profile", [True, None, [], {}, "typed_native_parameters/v2"])
def test_unknown_schema_profiles_fail_without_dispatch(tmp_path, profile):
    with pytest.raises(ValueError, match="action schema"):
        action_tool(agent(tmp_path)._action_tool(), profile)


def test_typed_schema_requires_visible_contract(tmp_path):
    config = load_segment_config(CONFIG, MODEL)
    config["local_inference"].update(
        action_reference="none", action_schema=TYPED, prompt_contract="grammar_only/v1"
    )
    with pytest.raises(ValueError, match="typed action schema"):
        validate_local_settings(config, MODEL)
