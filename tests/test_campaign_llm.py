import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from fort_gym.bench.agent.campaign_llm import CampaignActionError, CampaignLLMAgent
from fort_gym.bench.agent.governed_llm import (
    DFHackGovernedLLMAgent,
    _submit_action_tool,
)


def agent(**kwargs):
    return CampaignLLMAgent(
        api_key="test-only-placeholder",
        model_override="test/model",
        memory_path=None,
        max_attempts=1,
        **kwargs,
    )


def response(payload):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            function=SimpleNamespace(
                                name="submit_action",
                                arguments=json.dumps(payload),
                            )
                        )
                    ],
                )
            )
        ]
    )


def test_campaign_tool_requires_gameplay_fields_only_and_preserves_legacy_tool():
    tool = agent()._action_tool()["function"]["parameters"]
    assert tool["required"] == ["type", "params", "advance_ticks"]
    assert "plan_review" not in tool["properties"]
    assert "last_action_review" not in tool["properties"]
    assert "plan_review" in _submit_action_tool()["function"]["parameters"]["required"]


@pytest.mark.parametrize("campaign", [False, True])
@pytest.mark.parametrize("model", ["test/model", "z-ai/glm-5.2"])
def test_actual_transport_uses_profile_grammar_without_changing_legacy(
    monkeypatch, campaign, model
):
    policy_class = CampaignLLMAgent if campaign else DFHackGovernedLLMAgent
    policy = policy_class(
        api_key="test-only", model_override=model, memory_path=None, max_attempts=1
    )
    requests = []
    monkeypatch.setattr(policy, "_dispatch_completion", lambda request: requests.append(request))
    policy._create_completion([{"role": "system", "content": "test prompt"}])
    request = requests[0]
    if model == "z-ai/glm-5.2":
        instruction = request["messages"][-1]["content"]
        assert ("Planning notes are optional" in instruction) is campaign
        assert "tools" not in request
    else:
        required = request["tools"][0]["function"]["parameters"]["required"]
        assert ("plan_review" in required) is not campaign
        assert request["tool_choice"]["function"]["name"] == "submit_action"


def test_valid_model_command_does_not_need_a_plan_review(monkeypatch):
    policy = agent()
    calls = []
    payload = {"type": "WAIT", "params": {}, "advance_ticks": 20}
    monkeypatch.setattr(
        policy, "_create_completion", lambda messages: calls.append(messages) or response(payload)
    )
    monkeypatch.setattr(
        policy, "_review_contract_errors", lambda *args: pytest.fail("No benchmark review gate")
    )
    control = {"agent_plan_control": {"review_due": True, "required_plan_decision": "revise"}}
    result = policy.decide("Observed fortress", control)
    assert result["type"] == "WAIT" and result["advance_ticks"] == 20
    assert len(calls) == 1
    assert policy.pop_tool_events()[-1]["output"]["grammar_valid"] is True


def test_optional_malformed_benchmark_metadata_does_not_veto_native_command(monkeypatch):
    policy = agent()
    payload = {
        "type": "DIG",
        "params": {"area": [4, 5, 6], "size": [1, 1, 1]},
        "advance_ticks": 200,
        "last_action_review": "My own free-form review",
        "plan_review": "Continue my plan",
        "objective": "Develop the settlement",
        "memory_update": "Remember my current plan",
    }
    monkeypatch.setattr(policy, "_create_completion", lambda messages: response(payload))
    result = policy.decide("Observed native wall", {})
    assert result["type"] == "DIG" and result["last_action_review"] is None
    assert policy._memory.gameplay_plan["objective"] == "Develop the settlement"
    event = policy.pop_tool_events()[-1]
    assert event["output"]["payload"]["last_action_review"] == payload["last_action_review"]


def test_schema_repair_describes_missing_fields_without_choosing_a_gameplay_action(monkeypatch):
    policy = agent()
    messages = []
    responses = iter(
        [
            response({"type": "DIG", "params": {}, "advance_ticks": 10}),
            response(
                {
                    "type": "BUILD",
                    "params": {"kind": "Bed", "x": 4, "y": 5, "z": 6},
                    "advance_ticks": 20,
                }
            ),
        ]
    )
    monkeypatch.setattr(
        policy,
        "_create_completion",
        lambda value: messages.append(deepcopy(value)) or next(responses),
    )
    result = policy.decide("Observed world", {})
    assert result["type"] == "BUILD" and result["params"]["x"] == 4
    correction = messages[-1][-1]["content"]
    assert "missing required fields: area, size" in correction
    assert "You choose the gameplay decision" in correction
    assert len(messages) == 2


@pytest.mark.parametrize("ticks", [True, None, -1, 2001])
def test_bad_gameplay_grammar_has_bounded_repairs_and_no_synthetic_wait(monkeypatch, ticks):
    policy = agent()
    calls = []
    monkeypatch.setattr(
        policy,
        "_create_completion",
        lambda messages: calls.append(1)
        or response({"type": "WAIT", "params": {}, "advance_ticks": ticks}),
    )
    with pytest.raises(CampaignActionError):
        policy.decide("Observed world", {})
    assert len(calls) == 3 and policy._pending is None


def test_provider_failure_propagates_without_a_gameplay_fallback(monkeypatch):
    policy = agent()

    def unavailable(messages):
        raise OSError("test provider unavailable")

    monkeypatch.setattr(policy, "_create_completion", unavailable)
    with pytest.raises(OSError, match="provider unavailable"):
        policy.decide("Observed world", {})
    assert policy._pending is None


def test_native_interact_still_requires_zero_advance(monkeypatch):
    policy = agent(schema_attempts=1)
    monkeypatch.setattr(
        policy,
        "_create_completion",
        lambda messages: response(
            {"type": "INTERACT", "params": {"operation": "cancel"}, "advance_ticks": 1}
        ),
    )
    with pytest.raises(CampaignActionError, match="INTERACT"):
        policy.decide("Observed dialog", {})


def test_campaign_policy_checkpoint_is_distinct_and_preserves_next_prompt(monkeypatch):
    original = agent()
    original.set_campaign_context(campaign_id="campaign")
    payload = {"type": "WAIT", "params": {}, "advance_ticks": 20, "objective": "My own objective"}
    monkeypatch.setattr(original, "_create_completion", lambda messages: response(payload))
    original.decide("Calendar 30:10\nPopulation 7\nFood 45", {})
    snapshot = original.export_campaign_state()
    assert snapshot["configuration"]["decision_profile"] == "campaign_action/v1"
    restored = agent()
    restored.restore_campaign_state(snapshot, campaign_id="campaign")
    messages = []
    for policy in (original, restored):
        monkeypatch.setattr(
            policy,
            "_create_completion",
            lambda value: messages.append(deepcopy(value)) or response(payload),
        )
        policy.decide("Calendar 30:30\nPopulation 7\nFood 45\nLast Action: WAIT accepted", {})
    assert messages[0] == messages[1]
    assert original.export_campaign_state() == restored.export_campaign_state()
    legacy = DFHackGovernedLLMAgent(
        api_key="test-only", model_override="test/model", memory_path=None
    )
    with pytest.raises(ValueError, match="configuration"):
        legacy.restore_campaign_state(snapshot, campaign_id="campaign")
