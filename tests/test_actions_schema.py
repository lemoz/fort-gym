from __future__ import annotations

from fort_gym.bench.env.actions import ACTION_TOOL_SPEC, system_prompt_v1


def test_action_tool_spec_structure() -> None:
    assert ACTION_TOOL_SPEC["name"] == "submit_action"
    params = ACTION_TOOL_SPEC["parameters"]
    assert params["type"] == "object"
    assert "type" in params["properties"]
    assert set(params["required"]) == {"type", "params"}


def test_system_prompt_mentions_single_action() -> None:
    assert "one action per step" in system_prompt_v1.lower()
