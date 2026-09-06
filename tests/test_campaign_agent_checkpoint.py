from __future__ import annotations

import json
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

import pytest

from fort_gym.bench.agent.governed_llm import (
    DFHackGovernedLLMAgent,
    GovernedBudgetCapError,
)
from fort_gym.bench.agent.memory import MemoryManager


def agent(**kwargs):
    return DFHackGovernedLLMAgent(
        api_key="test-secret-never-serialize",
        model_override="test/model",
        memory_path=None,
        memory_window=3,
        **kwargs,
    )


def populated_agent():
    result = agent()
    result.set_campaign_context(campaign_id="fort-1")
    for step in range(5):
        result._memory.add_step(
            f"observation {step}", {"type": "WAIT", "params": {}}, f"outcome {step}"
        )
    result._memory.remember_poi(label="Still", x=10, y=20, z=1)
    result._pending = {
        "observation_digest": "food 15, drinks 20",
        "action": {"type": "ORDER", "params": {"job": "brew_drink", "quantity": 5}},
    }
    result._total_tokens = 1234
    result._total_cost_usd = Decimal("0.123456789123456789")
    result._returned_response_count = 5
    result._accounted_response_count = 4
    return result


def test_memory_checkpoint_keeps_recent_context_legacy_export_does_not():
    memory = MemoryManager(window_size=3)
    for step in range(5):
        memory.add_step(f"obs {step}", {"nested": {"x": step}}, f"result {step}")
    before = memory.get_context()
    checkpoint = memory.export_checkpoint()
    assert "recent_steps" not in memory.to_dict()
    restored = MemoryManager(window_size=3)
    restored.restore_checkpoint(json.loads(json.dumps(checkpoint)))
    assert restored.get_context() == before
    memory.add_step("next", {"type": "WAIT"}, "advanced")
    restored.add_step("next", {"type": "WAIT"}, "advanced")
    assert restored.export_checkpoint() == memory.export_checkpoint()


def test_export_is_detached_from_mutable_memory():
    memory = MemoryManager()
    memory.add_step("before", {"params": {"amount": 1}}, "result")
    snapshot = memory.export_checkpoint()
    snapshot["recent_steps"][0]["action"]["params"]["amount"] = 999
    assert memory.recent_steps[0].action["params"]["amount"] == 1


def test_memory_invalid_checkpoint_does_not_partially_mutate_state():
    memory = MemoryManager()
    memory.add_step("original", {"type": "WAIT"}, "advanced")
    original = memory.export_checkpoint()
    broken = deepcopy(original)
    broken["summary"] = "must not replace original"
    broken["recent_steps"][0]["step"] = True
    with pytest.raises(ValueError):
        memory.restore_checkpoint(broken)
    assert memory.export_checkpoint() == original


def test_memory_config_mismatch_is_explicit():
    with pytest.raises(ValueError, match="configuration"):
        MemoryManager(window_size=1).restore_checkpoint(MemoryManager().export_checkpoint())


def test_disabled_memory_roundtrips_without_enabling_it():
    memory = MemoryManager(window_size=0)
    restored = MemoryManager(window_size=0)
    restored.restore_checkpoint(memory.export_checkpoint())
    restored.add_step("observation", {"type": "WAIT"}, "result")
    assert restored.get_context() == ""


def test_agent_roundtrip_restores_context_pending_outcome_and_exact_cost():
    original = populated_agent()
    snapshot = json.loads(json.dumps(original.export_campaign_state()))
    restored = agent()
    restored.restore_campaign_state(snapshot, campaign_id="fort-1")
    assert restored.export_campaign_state() == snapshot
    assert restored._memory.get_context() == original._memory.get_context()
    assert restored._total_cost_usd == Decimal("0.123456789123456789")
    restored.set_run_context(run_id="next-segment")
    assert restored._total_tokens == 1234
    assert restored._session_id == "fort-gym:campaign:fort-1"
    assert restored._accounted_response_count == 4
    assert restored._returned_response_count == 5


def test_pending_action_is_reviewed_once_not_reissued_on_restore():
    snapshot = populated_agent().export_campaign_state()
    restored = agent()
    restored.restore_campaign_state(snapshot, campaign_id="fort-1")
    before = restored._memory._step_counter
    restored._record_previous_outcome("LAST ACTION: ORDER accepted; five drinks produced")
    restored._record_previous_outcome("LAST ACTION: ORDER accepted; five drinks produced")
    assert restored._memory._step_counter == before + 1
    assert restored._pending is None


def test_snapshot_has_no_transport_client_or_credentials():
    original = populated_agent()
    original._client = object()
    encoded = json.dumps(original.export_campaign_state())
    assert "test-secret-never-serialize" not in encoded
    assert "_client" not in encoded
    assert "api_key" not in encoded


def test_independent_runs_still_reset_usage():
    original = agent()
    original.set_run_context(run_id="first")
    original._total_tokens = 100
    original._total_cost_usd = Decimal(1)
    original.set_run_context(run_id="second")
    assert original._total_tokens == 0
    assert original._total_cost_usd == 0


@pytest.mark.parametrize("cost", ["NaN", "Infinity", "-1", "unknown"])
def test_invalid_cost_does_not_replace_agent_state(cost):
    snapshot = populated_agent().export_campaign_state()
    snapshot["usage"]["total_cost_usd"] = cost
    restored = agent()
    before = restored._memory.export_checkpoint()
    with pytest.raises(ValueError, match="cost"):
        restored.restore_campaign_state(snapshot, campaign_id="fort-1")
    assert restored._memory.export_checkpoint() == before
    assert restored._campaign_id is None


def test_cannot_restore_other_model_or_campaign():
    snapshot = populated_agent().export_campaign_state()
    with pytest.raises(ValueError, match="different campaign"):
        agent().restore_campaign_state(snapshot, campaign_id="other")
    snapshot["configuration"]["model"] = "different/model"
    with pytest.raises(ValueError, match="configuration"):
        agent().restore_campaign_state(snapshot, campaign_id="fort-1")


def test_budget_allowance_can_change_but_usage_does_not_reset():
    snapshot = populated_agent().export_campaign_state()
    restored = agent(max_cost_usd=50)
    restored.restore_campaign_state(snapshot, campaign_id="fort-1")
    assert restored._max_cost_usd == 50
    assert restored._total_cost_usd == Decimal(snapshot["usage"]["total_cost_usd"])


def test_restored_usage_is_enforced_before_any_further_provider_dispatch():
    restored = agent(max_cost_usd=0.1)
    restored.restore_campaign_state(populated_agent().export_campaign_state(), campaign_id="fort-1")
    restored.set_run_context(run_id="new-segment")
    with pytest.raises(GovernedBudgetCapError):
        restored._pre_dispatch_gate()
    assert restored._returned_response_count == 5


def test_campaign_must_be_explicit_and_cannot_change_on_a_live_agent():
    original = agent()
    with pytest.raises(ValueError, match="campaign context"):
        original.export_campaign_state()
    original.set_campaign_context(campaign_id="one")
    with pytest.raises(ValueError, match="fresh agent"):
        original.set_campaign_context(campaign_id="two")


def test_restore_cannot_roll_back_spending_on_an_already_used_agent():
    original = populated_agent()
    snapshot = original.export_campaign_state()
    original._total_tokens += 100
    with pytest.raises(ValueError, match="rolling back spending"):
        original.restore_campaign_state(snapshot, campaign_id="fort-1")
    assert original._total_tokens == 1334


def test_entering_campaign_mode_cannot_reset_existing_usage():
    original = agent()
    original._total_tokens = 500
    with pytest.raises(ValueError, match="fresh agent"):
        original.set_campaign_context(campaign_id="one")
    assert original._total_tokens == 500


def test_campaign_memory_cannot_leak_through_legacy_shared_memory_file(tmp_path):
    original = DFHackGovernedLLMAgent(
        api_key="test-only", memory_path=str(tmp_path / "legacy.json")
    )
    with pytest.raises(ValueError, match="memory_path=None"):
        original.set_campaign_context(campaign_id="one")
    with pytest.raises(ValueError, match="memory_path=None"):
        original.restore_campaign_state(
            populated_agent().export_campaign_state(), campaign_id="fort-1"
        )


def test_generic_agent_checkpoint_support_is_explicit():
    from fort_gym.bench.agent.base import RandomAgent

    with pytest.raises(NotImplementedError, match="persistent campaigns"):
        RandomAgent().set_campaign_context(campaign_id="one")


def test_restored_agent_sends_same_next_decision_context(monkeypatch):
    original = populated_agent()
    restored = agent()
    restored.restore_campaign_state(original.export_campaign_state(), campaign_id="fort-1")
    restored.set_run_context(run_id="resumed-segment")
    payload = {"type": "WAIT", "params": {}, "advance_ticks": 1000, "intent": "Observe"}
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            function=SimpleNamespace(
                                name="submit_action", arguments=json.dumps(payload)
                            )
                        )
                    ],
                )
            )
        ]
    )
    messages = []

    def complete(request):
        messages.append(deepcopy(request))
        return response

    monkeypatch.setattr(original, "_create_completion", complete)
    monkeypatch.setattr(restored, "_create_completion", complete)
    observation = "Current fortress state\nLast action: ORDER accepted\nFood 20, drink 25"
    assert original.decide(observation, {}) == restored.decide(observation, {})
    assert messages[0] == messages[1]
    assert original._memory.export_checkpoint() == restored._memory.export_checkpoint()
