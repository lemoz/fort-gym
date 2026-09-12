import json
import shutil
from copy import deepcopy
from types import SimpleNamespace

import pytest

from fort_gym.bench.run.campaign_checkpoint import verify_checkpoint
from fort_gym.bench.run.campaign_loop import CampaignLoop
from fort_gym.bench.run.campaign_save import CampaignSaveError
from fort_gym.bench.run.keyboard_checkpoint_recovery import (
    compare_reloaded_observations, inspect_settled_checkpoint_source, recover_settled_checkpoint,
)
from fort_gym.bench.run.keyboard_segment import run_keyboard_segment
from tests.test_keyboard_runtime import CONDITION, environment, policy


@pytest.fixture(params=[False, True], ids=["continuous", "inherited-loss"])
def failed_save(tmp_path, request):
    env = environment()
    loop = CampaignLoop(campaign_id="checkpoint-test", agent=policy(CONDITION), environment=env,
                        output=tmp_path / "initial", observation_profile=CONDITION["observation_profile"],
                        advance_policy=CONDITION["advance_policy"])
    if request.param:
        loop.discontinuities = [{
            "schema_version": "fortgym.native-save-loss-restart/v1",
            **{key: "a" * 64 for key in ("checkpoint_sha256", "source_result_sha256",
                                         "source_trace_sha256", "source_usage_sha256")},
            "restored_next_step": 1, "lost_trace_next_step": 2, "lost_elapsed_ticks": 10,
            "memory_policy": "restore_checkpoint_memory", "actions_replayed": False,
            "uninterrupted_campaign": False,
            "retained_usage": deepcopy(loop.agent.export_campaign_state()["usage"]),
        }]
    loop.step()
    parent = tmp_path / "parent"
    loop.checkpoint(parent, snapshotter=env, code_revision="0" * 40)

    def failed(destination):
        env.capture(destination)
        raise CampaignSaveError("Native screen changed during menu-preserving save")

    segment = tmp_path / "failed"
    result = run_keyboard_segment(agent=policy(CONDITION), environment=env,
        snapshotter=SimpleNamespace(capture=failed), output=segment, condition=CONDITION,
        checkpoint=parent, latest_usage=loop.journal, steps=3, expected_cursor=1, revision="1" * 40)
    assert result["status"] == "checkpoint_failed"
    env.expected_dfroot = tmp_path / "loaded-runtime"
    loaded = env.expected_dfroot / "data/save/campaign-resume"
    loaded.parent.mkdir(parents=True)
    shutil.copytree(segment / "checkpoint/game", loaded)
    return parent, segment, env


def recover(tmp_path, failed_save, **kwargs):
    parent, segment, env = failed_save
    return recover_settled_checkpoint(
        plan=inspect_settled_checkpoint_source(parent=parent, segment=segment),
        parent=parent, segment=segment,
        agent=policy(CONDITION, lambda *_: pytest.fail("Recovery must not call a model")),
        environment=env, snapshotter=SimpleNamespace(dfroot=env.expected_dfroot, capture=env.capture),
        native_probe=lambda: {"dfroot": str(env.expected_dfroot), "paused": True, "pending": False},
        output=tmp_path / "recovered", revision="2" * 40, **kwargs)


def test_settled_recovery_preserves_full_trace_memory_usage_and_normal_resume(tmp_path, failed_save):
    parent, segment, env = failed_save
    actions = deepcopy(env.actions)
    result = recover(tmp_path, failed_save)
    target = tmp_path / "recovered/checkpoint"
    checked = verify_checkpoint(target)
    assert checked["payload"]["parent_sha256"] == verify_checkpoint(parent)["sha256"]
    assert result["next_step"] == 4 and result["elapsed_ticks"] == 40
    assert result["model_calls"] == result["replayed_actions"] == result["new_ticks_requested"] == 0
    assert env.actions == actions and result["usage"]["total_tokens"] == 400
    for name in ("trace.jsonl", "usage.jsonl"):
        assert (target / name).read_bytes() == (segment / "loop" / name).read_bytes()
    assert json.loads((target / "agent.json").read_text()) == json.loads((segment / "agent-after.json").read_text())
    resumed = CampaignLoop.resume(target, agent=policy(CONDITION), environment=env,
                                 output=tmp_path / "next", latest_usage_path=target / "usage.jsonl")
    resumed.step()
    assert resumed.next_step == 5 and resumed.agent.usage["total_tokens"] == 500
    assert resumed.discontinuities == json.loads((parent / "runner.json").read_text()).get("discontinuities", [])


@pytest.mark.parametrize("name,field,value", [
    ("result.json", "checkpoint_verified", True),
    ("result.json", "status", "failed"),
    ("result.json", "next_step", 3),
    ("result.json", "recovery_requires_reconciliation", True),
    ("result.json", "checkpoint_error", "other failure"),
    ("agent-after.json", "memory", "invented"),
    ("native-after.json", "year_tick", 123),
])
def test_invalid_settled_source_is_not_recoverable(failed_save, name, field, value):
    parent, segment, _ = failed_save
    path = segment / name
    data = json.loads(path.read_text())
    data[field] = value
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        inspect_settled_checkpoint_source(parent=parent, segment=segment)


def test_changed_loaded_native_files_are_rejected_before_save(tmp_path, failed_save):
    _, _, env = failed_save
    (env.expected_dfroot / "data/save/campaign-resume/world.sav").write_text("changed")
    with pytest.raises(ValueError, match="native files"):
        recover(tmp_path, failed_save)
    assert not (tmp_path / "recovered").exists()


def test_changed_source_after_plan_is_rejected(tmp_path, failed_save):
    parent, segment, env = failed_save
    plan = inspect_settled_checkpoint_source(parent=parent, segment=segment)
    (segment / "checkpoint/game/world.sav").write_text("changed")
    with pytest.raises(ValueError, match="source changed"):
        recover_settled_checkpoint(plan=plan, parent=parent, segment=segment, agent=None,
            environment=env, snapshotter=None, native_probe=None, output=tmp_path / "out", revision="2"*40)


def observations():
    before = {"year": 30, "year_tick": 123, "population": 7, "viewscreen_type": "unit",
        "crew": {"jobs": {"construct_building_walk_group_connected": 1,
            "construct_building_walk_group_disconnected": 0, "construct_building_walk_group_unknown": 0,
            "entries": [{"id": 42, "target_walk_group_connectivity": "connected",
                         "walk_group_connectivity": "connected"}]}}}
    after = deepcopy(before)
    after["viewscreen_type"] = "dwarfmode"
    jobs = after["crew"]["jobs"]
    jobs["construct_building_walk_group_connected"] = 0
    jobs["construct_building_walk_group_unknown"] = 1
    jobs["entries"][0]["target_walk_group_connectivity"] = "unknown"
    jobs["entries"][0]["walk_group_connectivity"] = "unknown"
    return before, after


def test_reindex_comparison_retains_only_documented_derived_differences():
    before, after = observations()
    checked = compare_reloaded_observations(before, after, reindex_pending=True)
    assert checked["persistent_observations_equal"] is True
    assert checked["all_observations_equal"] is False
    assert len(checked["changed_paths"]) == len(checked["expected_derived_paths"]) == 4
    assert compare_reloaded_observations(before, after, reindex_pending=False)["persistent_observations_equal"] is False


@pytest.mark.parametrize("change", ["population", "job_id", "counter_total", "connectivity", "missing", "boolean"])
def test_pending_reindex_cannot_hide_persistent_changes(change):
    before, after = observations()
    jobs = after["crew"]["jobs"]
    if change == "population":
        after["population"] = 8
    elif change == "job_id":
        jobs["entries"][0]["id"] = 43
    elif change == "counter_total":
        jobs["construct_building_walk_group_unknown"] = 2
    elif change == "connectivity":
        jobs["entries"][0]["target_walk_group_connectivity"] = "disconnected"
    elif change == "missing":
        jobs["entries"].clear()
    else:
        jobs["construct_building_walk_group_unknown"] = True
    assert compare_reloaded_observations(before, after, reindex_pending=True)["persistent_observations_equal"] is False
