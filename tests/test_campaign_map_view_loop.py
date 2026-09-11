"""Model-selected inspection continuity with synthetic game and model doubles."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from fort_gym.bench.env.campaign_encoder import encode_campaign_observation
from fort_gym.bench.env.campaign_view import DECISION_PROFILE, OBSERVATION_PROFILE, MAP_SCHEMA
from fort_gym.bench.run.campaign_advance import MODEL_REQUESTED
from fort_gym.bench.run.campaign_loop import CampaignLoop
from fort_gym.bench.run.campaign_config import load_segment_config
from tests.test_campaign_loop import TestAgent, TestEnvironment
from tests.test_campaign_map_view import SELECTION, action, receipt


class ViewEnvironment(TestEnvironment):
    def __init__(self):
        super().__init__()
        self.map_reads = []
        self.advances = []

    def inspect_map(self, selection):
        self.map_reads.append(deepcopy(selection))
        if selection is not None and selection["origin"][0] >= 64:
            return {
                "schema_version": MAP_SCHEMA,
                "ok": False,
                "error": "view_rectangle_outside_map",
            }
        return receipt(selection, self.state)

    def advance(self, ticks, state):
        self.advances.append(ticks)
        return super().advance(ticks, state)


class ViewAgent(TestAgent):
    def decide(self, text, observation):
        result = super().decide(text, observation)
        if self.count == 1:
            result.update(action())
        return result


def loop(tmp_path, agent=None, environment=None):
    return CampaignLoop(
        campaign_id="view-test",
        agent=agent or ViewAgent(),
        environment=environment or ViewEnvironment(),
        output=tmp_path / "campaign",
        observation_profile=OBSERVATION_PROFILE,
        advance_policy=MODEL_REQUESTED,
    )


def test_model_view_changes_only_observation_and_persists_after_a_world_action(tmp_path):
    run = loop(tmp_path)
    before = deepcopy(run.environment.state)
    selected = run.step()
    assert selected["action"]["type"] == "VIEW" and selected["execute"]["accepted"]
    assert selected["observation"]["map_view"]["selection"] is None
    assert selected["state_after_advance"]["map_view"]["selection"] == SELECTION
    assert run.environment.actions == [] and run.environment.advances == [0]
    assert run.environment.state == before and run.committed_elapsed_ticks == 0
    assert run.observation_view == SELECTION
    next_action = run.step()
    assert next_action["observation"]["map_view"]["selection"] == SELECTION
    assert next_action["observation"]["campaign_clock"]["elapsed_ticks"] == 0
    assert next_action["tick_advance"]["ticks_advanced"] == 200
    assert run.environment.actions == ["test decision 2"]
    assert run.agent.export_campaign_state()["usage"]["returned_responses"] == 2


def test_view_checkpoint_resume_matches_uninterrupted_next_decision(tmp_path):
    run = loop(tmp_path)
    run.step()
    checkpoint = tmp_path / "checkpoint"
    run.checkpoint(checkpoint, snapshotter=run.environment, code_revision="view-test")
    saved = json.loads((checkpoint / "runner.json").read_text())
    assert saved["observation_view"] == SELECTION
    environment = ViewEnvironment()
    environment.state = json.loads((checkpoint / "game/world.sav").read_text())
    resumed = CampaignLoop.resume(
        checkpoint,
        agent=ViewAgent(),
        environment=environment,
        output=tmp_path / "resumed",
        latest_usage_path=run.journal,
        observation_profile=OBSERVATION_PROFILE,
    )
    assert resumed.observation_view == SELECTION and resumed.committed_elapsed_ticks == 0
    assert resumed.step() == run.step()
    assert resumed.agent.prompts == [run.agent.prompts[-1]]
    assert environment.actions == ["test decision 2"]  # No replay of the VIEW or prior action.


def test_rejected_view_keeps_prior_selection_and_remains_action_feedback(tmp_path):
    class InvalidSecond(ViewAgent):
        def decide(self, text, observation):
            result = super().decide(text, observation)
            if self.count == 2:
                result.update(action({"origin": [64, 0, 0], "size": [1, 1]}))
            return result

    run = loop(tmp_path, agent=InvalidSecond())
    run.step()
    rejected = run.step()
    assert rejected["execute"]["accepted"] is False
    assert rejected["execute"]["why"] == "view_rectangle_outside_map"
    assert rejected["tick_advance"]["ticks_advanced"] == 0
    assert run.observation_view == SELECTION and run.environment.actions == []
    assert run.at_boundary and not run.failed
    following = run.step()
    assert following["observation"]["last_action_result"] == rejected["execute"]
    assert following["observation"]["map_view"]["selection"] == SELECTION
    assert following["observation"]["campaign_clock"]["completed_decisions"] == 2


def test_missing_inspection_capability_fails_before_campaign_output(tmp_path):
    with pytest.raises(ValueError, match="capability"):
        loop(tmp_path, environment=TestEnvironment())
    assert not (tmp_path / "campaign").exists()


def test_inspecting_a_paused_dialog_never_dismisses_it(tmp_path):
    environment = ViewEnvironment()
    environment.state["viewscreen_type"] = "viewscreen_textviewerst"
    run = loop(tmp_path, environment=environment)
    row = run.step()
    assert row["execute"]["accepted"] and row["tick_advance"]["ticks_advanced"] == 0
    assert environment.state["viewscreen_type"] == "viewscreen_textviewerst"
    assert "VIEW only reads terrain" in row["observation"]["time_control"]["semantics"]
    assert not environment.actions


def test_bad_post_action_map_keeps_native_receipt_and_is_a_runtime_failure(tmp_path):
    from fort_gym.bench.env.campaign_view import MapObservationError
    from fort_gym.bench.run.campaign_feed import failure_kind

    class BrokenAfterAdvance(ViewEnvironment):
        def inspect_map(self, selection):
            result = super().inspect_map(selection)
            if any(self.advances):
                result["year"] += 1
            return result

    run = loop(tmp_path, environment=BrokenAfterAdvance())
    run.step()
    with pytest.raises(MapObservationError) as caught:
        run.step()
    assert (
        failure_kind({"status": "failed", "terminal_code": caught.value.terminal_code}) == "runtime"
    )
    failure = json.loads((run.output / "failures.jsonl").read_text())
    assert failure["action"]["type"] == "WAIT"
    assert failure["tick_receipt"]["ticks_advanced"] == 200
    assert failure["native_after"]["year_tick"] - failure["native_before"]["year_tick"] == 200
    assert run.failed and not run.at_boundary and run.next_step == 1
    assert run.observation_view == SELECTION
    assert run.agent.export_campaign_state()["usage"]["returned_responses"] == 2


def test_selected_view_is_digest_bound_in_checkpoint(tmp_path):
    from fort_gym.bench.run.campaign_checkpoint import CampaignCheckpointError, verify_checkpoint

    run = loop(tmp_path)
    run.step()
    checkpoint = tmp_path / "checkpoint"
    run.checkpoint(checkpoint, snapshotter=run.environment, code_revision="view-test")
    state = json.loads((checkpoint / "runner.json").read_text())
    state["observation_view"]["origin"][0] = 2
    (checkpoint / "runner.json").write_text(json.dumps(state))
    with pytest.raises(CampaignCheckpointError, match="runner.json"):
        verify_checkpoint(checkpoint)


@pytest.mark.parametrize("old_profile", ["campaign_state/v1", "campaign_state/v2"])
def test_old_profiles_never_query_or_expose_inspection(old_profile, tmp_path):
    environment = ViewEnvironment()
    run = CampaignLoop(
        campaign_id="old-profile",
        agent=TestAgent(),
        environment=environment,
        output=tmp_path / "old",
        observation_profile=old_profile,
    )
    row = run.step()
    assert environment.map_reads == [] and "map_view" not in row["observation"]
    checkpoint = tmp_path / "checkpoint"
    run.checkpoint(checkpoint, snapshotter=environment, code_revision="test")
    assert "observation_view" not in json.loads((checkpoint / "runner.json").read_text())


def test_encoder_exposes_inspection_only_in_v3_and_keeps_fort_overview():
    state = {
        "year": 30,
        "year_tick": 1,
        "fort": {"map_rows": ["#."], "map_origin": [1, 2, 3]},
        "map_view": {"selection": SELECTION, "native": receipt()},
    }
    for profile in ("campaign_state/v1", "campaign_state/v2", OBSERVATION_PROFILE):
        _, observed = encode_campaign_observation(
            state,
            screen_text="test",
            action_history=[],
            last_action_result=None,
            profile=profile,
            committed_elapsed_ticks=20,
            completed_decisions=1,
        )
        assert observed["fort"] == state["fort"]
        assert ("map_view" in observed) == (profile == OBSERVATION_PROFILE)
        if profile == OBSERVATION_PROFILE:
            assert observed["campaign_clock"]["elapsed_ticks"] == 20
            observed["map_view"]["selection"]["origin"][0] = 3
            assert SELECTION["origin"][0] == 40


@pytest.mark.parametrize(
    "filename",
    ["development_autonomous_v1.json", "local_native_qwen35_year_two_reasoning_budget_v1.json"],
)
def test_configuration_requires_matching_inspection_action_and_observation(tmp_path, filename):
    root = Path(__file__).resolve().parents[1] / "experiments/campaigns"
    config = json.loads((root / filename).read_text())
    config.update(decision_profile=DECISION_PROFILE, observation_profile=OBSERVATION_PROFILE)
    path = tmp_path / "condition.json"
    path.write_text(json.dumps(config))
    assert load_segment_config(path, config["models"][0]) == config
    for decision, observation in [
        ("campaign_action/v1", OBSERVATION_PROFILE),
        (DECISION_PROFILE, "campaign_state/v2"),
    ]:
        path.write_text(
            json.dumps({**config, "decision_profile": decision, "observation_profile": observation})
        )
        with pytest.raises(ValueError, match="profiles"):
            load_segment_config(path, config["models"][0])
