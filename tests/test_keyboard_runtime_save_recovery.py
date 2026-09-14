"""Latest runtime files require an explicitly declared, attested source kind."""

import json
import shutil
from types import SimpleNamespace

import pytest

from fort_gym.bench.run.campaign_checkpoint import verify_checkpoint
from fort_gym.bench.run.keyboard_checkpoint_recovery import (
    RUNTIME_SOURCE, inspect_settled_checkpoint_source, recover_settled_checkpoint,
)
from tests.test_keyboard_checkpoint_recovery import failed_save as failed_save
from tests.test_keyboard_runtime import CONDITION, policy


@pytest.fixture
def retained_runtime(failed_save):
    parent, old_segment, env = failed_save
    segment = old_segment.with_name("segment-0")
    old_segment.rename(segment)
    saved = segment.parent / "runtime-0/runtime/data/save/campaign-resume"
    saved.parent.mkdir(parents=True)
    shutil.move(segment / "checkpoint/game", saved)
    result = json.loads((segment / "result.json").read_text())
    result["checkpoint_error"] = "Native menu identity changed during save"
    result["checkpoint_error_type"] = "CampaignSaveError"
    (segment / "result.json").write_text(json.dumps(result))
    native = json.loads((segment / "native-after.json").read_text())
    (segment / "save-attempt.json").write_text(json.dumps({
        "schema_version": "fortgym.native-menu-save-attempt/v1", "world_before": native,
    }))
    (segment.parent / "window.json").write_text(json.dumps({
        "snapshot_profile": "native_menu_preserving_save/v2",
    }))
    return parent, segment, saved, env


def test_runtime_save_needs_explicit_source_then_preserves_settled_history(tmp_path, retained_runtime):
    parent, segment, saved, env = retained_runtime
    with pytest.raises(ValueError, match="settled native checkpoint-validation"):
        inspect_settled_checkpoint_source(parent=parent, segment=segment)
    plan = inspect_settled_checkpoint_source(parent=parent, segment=segment, source_kind=RUNTIME_SOURCE)
    assert plan["schema_version"] == "fortgym.settled-keyboard-checkpoint-recovery/v2"
    assert plan["source_kind"] == RUNTIME_SOURCE
    assert set(plan["source_files"]) >= {"save-attempt.json", "../window.json"}
    result = recover_settled_checkpoint(
        plan=plan, parent=parent, segment=segment,
        agent=policy(CONDITION, lambda *_: pytest.fail("Recovery must not call a model")),
        environment=env, snapshotter=SimpleNamespace(dfroot=env.expected_dfroot, capture=env.capture),
        native_probe=lambda: {"dfroot": str(env.expected_dfroot), "paused": True, "pending": False},
        output=tmp_path / "recovered", revision="2" * 40,
    )
    assert result["schema_version"] == plan["schema_version"]
    assert result["next_step"] == 4 and result["elapsed_ticks"] == 40
    assert result["model_calls"] == result["replayed_actions"] == result["new_ticks_requested"] == 0
    checked = verify_checkpoint(tmp_path / "recovered/checkpoint")
    assert checked["payload"]["parent_sha256"] == verify_checkpoint(parent)["sha256"]
    for name in ("trace.jsonl", "usage.jsonl"):
        assert (tmp_path / "recovered/checkpoint" / name).read_bytes() == (segment / "loop" / name).read_bytes()
    assert inspect_settled_checkpoint_source(parent=parent, segment=segment, source_kind=RUNTIME_SOURCE) == plan


@pytest.mark.parametrize("change", ["missing_world", "changed_world", "changed_after", "wrong_profile", "ambiguous_copy", "symlink"])
def test_runtime_source_cannot_bypass_retained_boundary_checks(retained_runtime, change):
    parent, segment, saved, env = retained_runtime
    attempt = json.loads((segment / "save-attempt.json").read_text())
    if change == "missing_world":
        del attempt["world_before"]
    elif change == "changed_world":
        attempt["world_before"]["year_tick"] += 1
    elif change == "changed_after":
        attempt["world_after"] = {"year_tick": 999}
    elif change == "wrong_profile":
        (segment.parent / "window.json").write_text('{"snapshot_profile": "native_quicksave/v1"}')
    elif change == "ambiguous_copy":
        shutil.copytree(saved, segment / "checkpoint/game")
    else:
        real = saved.with_name("other-save")
        saved.rename(real)
        saved.symlink_to(real, target_is_directory=True)
    (segment / "save-attempt.json").write_text(json.dumps(attempt))
    with pytest.raises((ValueError, RuntimeError)):
        inspect_settled_checkpoint_source(parent=parent, segment=segment, source_kind=RUNTIME_SOURCE)


def test_runtime_source_change_after_plan_is_rejected_before_observation(tmp_path, retained_runtime):
    parent, segment, saved, env = retained_runtime
    plan = inspect_settled_checkpoint_source(parent=parent, segment=segment, source_kind=RUNTIME_SOURCE)
    (saved / "world.sav").write_text("changed")
    with pytest.raises(ValueError, match="source changed"):
        recover_settled_checkpoint(plan=plan, parent=parent, segment=segment, agent=None,
            environment=env, snapshotter=None, native_probe=None, output=tmp_path / "out", revision="2" * 40)
