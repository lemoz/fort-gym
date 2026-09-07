"""Regression for the recorded liaison stop; doubles are not native recovery proof."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from fort_gym.bench.env.actions import INTERACT_ALLOWED_VIEWSCREEN_TYPES
from fort_gym.bench.run.campaign_advance import ACCEPTED_ONLY, MODEL_REQUESTED, requested_ticks
from fort_gym.bench.run.campaign_environment import NativeCampaignEnvironment
from fort_gym.bench.run.campaign_loop import CampaignLoop, reconciled_usage
from tests.test_campaign_loop import TestAgent


@pytest.mark.parametrize("viewscreen", sorted(INTERACT_ALLOWED_VIEWSCREEN_TYPES))
@pytest.mark.parametrize("action_type", ["WAIT", "DIG", "BUILD", "ORDER", "LABOR", "FARM"])
def test_dialog_rejects_world_commands_without_dispatch_or_clock(viewscreen, action_type):
    env = NativeCampaignEnvironment.__new__(NativeCampaignEnvironment)
    env._verify_runtime = lambda: None
    env.executor = SimpleNamespace(apply=lambda *a, **k: pytest.fail("No native command"))
    state = {"viewscreen_type": viewscreen, "pause_state": True}
    action = {"type": action_type, "params": {}, "advance_ticks": 2500}
    before = deepcopy(action)
    result = env.apply(action, state)
    assert result["accepted"] is False
    assert result["command_mutation"] == "not_attempted"
    assert result["simulation_blocked_by"] == viewscreen
    assert "INTERACT" in result["why"]
    assert action == before  # Retain the real model request, not a replacement action.
    for policy in (ACCEPTED_ONLY, MODEL_REQUESTED):
        assert requested_ticks(2500, result, policy) == 0


@pytest.mark.parametrize(
    "state",
    [
        {},
        {"viewscreen_type": "viewscreen_dwarfmodest", "pause_state": True},
        {"viewscreen_type": "unknown", "pause_state": True},
        {"viewscreen_type": "viewscreen_textviewerst", "pause_state": False},
        {"viewscreen_type": "viewscreen_textviewerst", "pause_state": 1},
    ],
)
def test_only_known_attested_paused_dialogs_receive_dialog_feedback(state):
    env = NativeCampaignEnvironment.__new__(NativeCampaignEnvironment)
    env._verify_runtime = lambda: None
    calls = []
    result = {"accepted": True}
    env.executor = SimpleNamespace(apply=lambda *a, **k: calls.append((a, k)) or result)
    assert env.apply({"type": "WAIT", "params": {}}, state) == result
    assert len(calls) == 1


@pytest.mark.parametrize("accepted", [True, False])
def test_model_interaction_still_goes_through_existing_native_legality(accepted):
    env = NativeCampaignEnvironment.__new__(NativeCampaignEnvironment)
    env._verify_runtime = lambda: None
    calls = []
    result = {"accepted": accepted, "result": {"ok": accepted}}
    env.executor = SimpleNamespace(apply=lambda *a, **k: calls.append((a, k)) or result)
    action = {"type": "INTERACT", "params": {"operation": "confirm"}, "advance_ticks": 0}
    state = {"viewscreen_type": "viewscreen_textviewerst", "pause_state": True}
    assert env.apply(action, state) == result
    assert calls == [((action,), {"backend": "dfhack", "state": state, "allow_interact": True})]


def test_uncertain_write_cannot_use_a_dialog_marker_to_hide_failure():
    execution = {
        "accepted": False,
        "simulation_blocked_by": "viewscreen_textviewerst",
        "result": {"ok": False, "command_mutation": "attempted"},
    }
    with pytest.raises(ValueError, match="definite"):
        requested_ticks(2500, execution, MODEL_REQUESTED)
    execution = {"accepted": False, "command_mutation": "not_attempted"}
    for marker in (None, "unknown", "viewscreen_dwarfmodest"):
        execution["simulation_blocked_by"] = marker
        assert requested_ticks(2500, execution, MODEL_REQUESTED) == 2500


def test_wait_on_recorded_dialog_remains_accounted_then_model_can_interact(tmp_path):
    # Exact public boundary from the terminal audit, not a new native run:
    # db4556fe1744e432f8e0c619dcc44e1e065f27b1 / experiments/evidence/
    # local_native_qwen35_year_two_dialog_failure_20260907.json
    # Original failure journal SHA256:
    # 8cba9c0789c2fc9ec2f8dd67c42881eaffdc17e61e56d247b4f1bf6b99bc3a19
    viewscreen = "viewscreen_textviewerst"

    class DialogAgent(TestAgent):
        def decide(self, text, observation):
            action = super().decide(text, observation)
            if self.count == 1:
                action["advance_ticks"] = 2500
            if self.count == 2:
                action.update(type="INTERACT", params={"operation": "confirm"}, advance_ticks=0)
            return action

    env = NativeCampaignEnvironment.__new__(NativeCampaignEnvironment)
    env._verify_runtime = lambda: None
    env.max_advance_ticks = 2500
    state = {
        "year": 30,
        "year_tick": 220140,
        "pause_state": True,
        "viewscreen_type": viewscreen,
        "population": 9,
        "stocks": {"drink": 25},
    }
    env.observe = lambda: deepcopy(state)
    env.screen = (
        lambda: "Test-only dialog"
        if state["viewscreen_type"] == viewscreen
        else "Test-only fortress"
    )
    calls = []

    def execute(action, **kwargs):
        calls.append(deepcopy(action))
        if action["type"] == "INTERACT":
            state["viewscreen_type"] = "viewscreen_dwarfmodest"
        return {"accepted": True}

    def advance(ticks, **kwargs):
        assert state["viewscreen_type"] == "viewscreen_dwarfmodest"
        state["year_tick"] += ticks
        client.last_tick_info = {"ok": True, "ticks_advanced": ticks}

    env.executor = SimpleNamespace(apply=execute)
    client = SimpleNamespace(advance=advance)
    env.client = client
    loop = CampaignLoop(
        campaign_id="dialog-feedback-test",
        agent=DialogAgent(),
        environment=env,
        output=tmp_path / "campaign",
        observation_profile="campaign_state/v1",
        advance_policy=MODEL_REQUESTED,
        max_advance_ticks=2500,
    )
    rejected = loop.step()
    assert calls == [] and rejected["execute"]["accepted"] is False
    assert rejected["action"]["advance_ticks"] == 2500
    assert rejected["tick_advance"]["ticks_advanced"] == 0
    assert loop.at_boundary and not loop.failed
    interacted = loop.step()
    assert interacted["action"]["type"] == "INTERACT"
    assert interacted["tick_advance"]["ticks_advanced"] == 0
    assert loop.agent.prompts[1][1]["last_action_result"] == rejected["execute"]
    assert "REJECTED" in loop.agent.prompts[1][0]
    played = loop.step()
    assert played["tick_advance"]["ticks_advanced"] == 200
    assert loop.next_step == 3 and loop.committed_elapsed_ticks == 200
    assert [action["type"] for action in calls] == ["INTERACT", "WAIT"]
    assert not (loop.output / "failures.jsonl").exists()
    agent = loop.agent.export_campaign_state()
    assert reconciled_usage(agent, loop.journal.read_bytes()) == agent["usage"]
    assert agent["usage"]["returned_responses"] == 3
    assert agent["usage"]["total_tokens"] == 30
