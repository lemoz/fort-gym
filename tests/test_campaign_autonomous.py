"""Configured policy + loop + checkpoint tests with a fake provider, never gameplay proof."""

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from fort_gym.bench.agent.campaign_llm import CampaignLLMAgent
from fort_gym.bench.config import get_settings
from scripts.campaign_development import make_agent
from scripts.campaign_segment import load_segment_config, run_segment
from tests.test_campaign_loop import TestEnvironment

CONFIG = (
    Path(__file__).resolve().parents[1] / "experiments/campaigns/development_autonomous_v1.json"
)
MODEL = "qwen/qwen3.8-flash"


@pytest.fixture
def condition(monkeypatch):
    monkeypatch.setenv("FORT_GYM_DISABLE_DOTENV", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-only-not-a-real-credential")
    get_settings.cache_clear()
    yield load_segment_config(CONFIG, MODEL)
    get_settings.cache_clear()


def fake_policy(config, output, monkeypatch, payload=None):
    policy = make_agent(config, MODEL, output / "spend.jsonl", persist_dispatches=True)
    requests = []

    def create(**request):
        requests.append(deepcopy(request))
        action = (
            payload if payload is not None else {"type": "WAIT", "params": {}, "advance_ticks": 20}
        )
        return SimpleNamespace(
            id=f"fake-generation-{policy.dispatches}",
            model=MODEL,
            choices=[
                SimpleNamespace(
                    finish_reason="tool_calls",
                    message=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                function=SimpleNamespace(
                                    name="submit_action", arguments=json.dumps(action)
                                )
                            )
                        ],
                    ),
                )
            ],
            usage=SimpleNamespace(total_tokens=10, cost=0.0001),
        )

    monkeypatch.setattr(
        policy,
        "_client_instance",
        lambda: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
    )
    monkeypatch.setattr(policy, "_rate_limit", lambda: None)
    return policy, requests


def run(output, policy, config, environment, **kwargs):
    return run_segment(
        agent=policy,
        environment=environment,
        snapshotter=environment,
        output=output,
        config=config,
        campaign_id="test-campaign",
        model=MODEL,
        revision="a" * 40,
        **kwargs,
    )


@pytest.mark.parametrize("dispatch_limit", [4, 8])
def test_configured_agent_uses_minimal_wire_schema_and_retains_usage_across_recovery(
    tmp_path,
    condition,
    monkeypatch,
    dispatch_limit,
):
    condition = {**condition, "max_dispatches": dispatch_limit}
    first = tmp_path / "first"
    first.mkdir()
    policy, requests = fake_policy(condition, first, monkeypatch)
    assert isinstance(policy, CampaignLLMAgent)
    result = run(first, policy, condition, TestEnvironment())
    assert result["status"] == "bounded_segment_complete" and result["new_checkpoint_verified"]
    assert len(requests) == 3 and result["usage"]["total_cost_usd"] == "0.0003"
    for request in requests:
        assert request["tools"][0]["function"]["parameters"]["required"] == [
            "type",
            "params",
            "advance_ticks",
        ]
        assert request["extra_body"]["provider"]["max_price"] == condition["provider_max_price"]
        assert "agent_plan_control" not in json.dumps(request)
        assert "G7" not in json.dumps(request)
    spend = [json.loads(line) for line in (first / "spend.jsonl").read_text().splitlines()]
    assert spend[0]["request_bytes"] == len(json.dumps(requests[0], ensure_ascii=True).encode())
    checkpoint = Path(result["checkpoint"])
    runner = json.loads((checkpoint / "runner.json").read_text())
    assert runner["observation_profile"] == "campaign_state/v1"
    second = tmp_path / "second"
    second.mkdir()
    restored, resumed_requests = fake_policy(condition, second, monkeypatch)
    environment = TestEnvironment()
    environment.state = json.loads((checkpoint / "game/world.sav").read_text())
    resumed = run(
        second,
        restored,
        condition,
        environment,
        checkpoint=checkpoint,
        latest_usage=first / "campaign/usage.jsonl",
    )
    steps = min(6, dispatch_limit)
    status = "budget_limited_pause" if dispatch_limit == 4 else "bounded_segment_complete"
    assert resumed["status"] == status and resumed["next_step"] == steps
    assert resumed["usage"] == {
        "total_tokens": steps * 10,
        "total_cost_usd": f"0.000{steps}",
        "returned_responses": steps,
        "accounted_responses": steps,
        "dispatched_requests": steps,
    }
    assert len(resumed_requests) == steps - 3 and len(environment.actions) == steps - 3
    assert "== MEMORY ==" in resumed_requests[0]["messages"][1]["content"]
    assert "Last Action: ACCEPTED" in resumed_requests[0]["messages"][1]["content"]
    assert restored._memory.failed_attempts == []


def test_malformed_commands_are_not_executed_or_counted_as_fortress_death(
    tmp_path, condition, monkeypatch
):
    policy, requests = fake_policy(
        condition, tmp_path, monkeypatch, payload={"type": "DIG", "params": {}, "advance_ticks": 20}
    )
    environment = TestEnvironment()
    result = run(tmp_path, policy, condition, environment)
    assert result["status"] == "failed" and result["terminal_code"] == "campaign_invalid_action"
    assert result["segment_committed_steps"] == 0 and len(requests) == 3
    assert environment.actions == [] and result["native_final"]["population"] == 7
    assert result["usage"]["total_cost_usd"] == "0.0003"
    assert result["new_checkpoint_verified"] is False
    failure = json.loads((tmp_path / "campaign/failures.jsonl").read_text())
    invalid = [
        event for event in failure["events"] if event["tool"] == "campaign_agent.action_response"
    ]
    assert len(invalid) == 3 and invalid[0]["output"]["payload"]["params"] == {}


def test_observation_profile_cannot_change_during_resume(tmp_path, condition, monkeypatch):
    from fort_gym.bench.run.campaign_loop import CampaignLoop

    first = tmp_path / "first"
    first.mkdir()
    policy, _ = fake_policy(condition, first, monkeypatch)
    result = run(first, policy, condition, TestEnvironment())
    restored, requests = fake_policy(condition, tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="observation profile"):
        CampaignLoop.resume(
            Path(result["checkpoint"]),
            agent=restored,
            environment=TestEnvironment(),
            output=tmp_path / "resumed",
            latest_usage_path=first / "campaign/usage.jsonl",
            observation_profile="governed_review/v1",
        )
    assert requests == [] and not (tmp_path / "resumed").exists()


def test_campaign_passes_the_current_paused_screen_to_native_dialog_validation(
    tmp_path,
    condition,
    monkeypatch,
):
    class DialogEnvironment(TestEnvironment):
        def screen(self):
            return "a - Finish peeking in on conversation"

        def apply(self, action, state):
            assert action["type"] == "INTERACT"
            assert state["screen_text"] == self.screen()
            assert state["pause_state"] is True
            return super().apply(action, state)

    policy, _ = fake_policy(
        condition,
        tmp_path,
        monkeypatch,
        payload={
            "type": "INTERACT",
            "params": {"operation": "finish_topic_meeting"},
            "advance_ticks": 0,
        },
    )
    result = run(tmp_path, policy, condition, DialogEnvironment())
    assert result["status"] == "bounded_segment_complete"
    assert result["native_final"]["year_tick"] == result["native_start"]["year_tick"]


def test_campaign_policy_cannot_accidentally_use_nonpersistent_legacy_runner(tmp_path, condition):
    with pytest.raises(ValueError, match="persistent dispatch"):
        make_agent(condition, MODEL, tmp_path / "spend.jsonl")


@pytest.mark.parametrize(
    "change",
    [
        {"observation_profile": "governed_review/v1"},
        {"decision_profile": "typo"},
        {"decision_profile": {}},
        {"observation_profile": []},
        {"schema_attempts": True},
        {"schema_attempts": 0},
        {"schema_attempts": 4},
    ],
)
def test_invalid_profile_pair_or_repair_allowance_rejected(tmp_path, condition, change):
    path = tmp_path / "condition.json"
    path.write_text(json.dumps({**condition, **change}))
    with pytest.raises(ValueError):
        load_segment_config(path, MODEL)
