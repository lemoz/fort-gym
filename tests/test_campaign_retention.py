"""Periodic-save and space-guard doubles; no native or model gameplay evidence."""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from fort_gym.bench.run import campaign_retention as retention
from fort_gym.bench.run.campaign_checkpoint import verify_checkpoint
from fort_gym.bench.run.campaign_config import load_segment_config, validate_bounds
from tests.test_campaign_loop import TestEnvironment
from tests.test_campaign_segment import segment

CONFIG = (
    Path(__file__).resolve().parents[1] / "experiments/campaigns/local_native_llama_long_v1.json"
)
MODEL = "fort-gym-qwen35-9b-q4-03b74727a860"


def condition(**updates):
    config = deepcopy(load_segment_config(CONFIG, MODEL))
    config.update(max_steps=6, max_dispatches=24, **updates)
    config["checkpoint_policy"]["interval_steps"] = 2
    return config


def test_periodic_siblings_preserve_final_handoff_and_same_live_environment(tmp_path):
    config = condition()
    env = TestEnvironment()
    first, root, agent = segment(tmp_path, config=config, environment=env)
    assert first["status"] == "bounded_segment_complete"
    assert len(env.actions) == agent.dispatches == 6
    assert [item["next_step"] for item in first["periodic_checkpoints"]] == [2, 4]
    final = verify_checkpoint(root / "checkpoint")
    assert final["payload"]["parent_sha256"] is None
    retention.verify_periodic(root, first, config, None)
    assert [
        json.loads(line) for line in (root / "periodic-checkpoints.jsonl").read_text().splitlines()
    ] == first["periodic_checkpoints"]
    for item in first["periodic_checkpoints"]:
        assert verify_checkpoint(root / item["relative_path"])["payload"]["parent_sha256"] is None
    # A new segment can load the final checkpoint with the unchanged handoff.
    restored = TestEnvironment()
    restored.state = json.loads((root / "checkpoint/game/world.sav").read_text())
    second, second_root, _ = segment(
        tmp_path,
        "second",
        config=config,
        environment=restored,
        checkpoint=root / "checkpoint",
        latest_usage=root / "campaign/usage.jsonl",
    )
    assert [item["next_step"] for item in second["periodic_checkpoints"]] == [8, 10]
    retention.verify_periodic(second_root, second, config, final["sha256"])
    assert (
        verify_checkpoint(second_root / "checkpoint")["payload"]["parent_sha256"] == final["sha256"]
    )


@pytest.mark.parametrize("mutation", ["missing", "path", "digest", "boolean", "game", "parent"])
def test_periodic_inventory_does_not_accept_missing_or_changed_evidence(tmp_path, mutation):
    config = condition()
    result, root, _ = segment(tmp_path, config=config)
    parent = None
    if mutation == "missing":
        result["periodic_checkpoints"] = []
    elif mutation == "path":
        result["periodic_checkpoints"][0]["relative_path"] = "../outside"
    elif mutation == "digest":
        result["periodic_checkpoints"][0]["file_sha256"] = "0" * 64
    elif mutation == "boolean":
        result["periodic_checkpoints"][0]["next_step"] = True
    elif mutation == "game":
        path = root / result["periodic_checkpoints"][0]["relative_path"]
        (path / "game/world.sav").write_text("changed test data")
    else:
        parent = "0" * 64
    with pytest.raises((ValueError, RuntimeError)):
        retention.verify_periodic(root, result, config, parent)


def test_low_space_stops_before_new_model_decision(tmp_path, monkeypatch):
    config = condition()
    monkeypatch.setattr(retention.shutil, "disk_usage", lambda path: SimpleNamespace(free=100))
    result, root, agent = segment(tmp_path, config=config)
    assert result["status"] == "budget_limited_pause"
    assert "free-space floor" in result["error"]
    assert agent.dispatches == 0 and result["segment_committed_steps"] == 0
    assert result["periodic_checkpoints"] == []
    assert not (root / "checkpoint").exists()


def test_prior_periodic_save_is_retained_but_not_claimed_as_latest_after_failure(tmp_path):
    class BrokenEnvironment(TestEnvironment):
        def apply(self, action, state):
            if len(self.actions) == 2:
                raise OSError("synthetic native failure")
            return super().apply(action, state)

    config = condition()
    result, root, agent = segment(tmp_path, config=config, environment=BrokenEnvironment())
    assert agent.dispatches == 3 and result["next_step"] == 2
    assert result["status"] == "failed" and result["recovery_requires_reconciliation"] is True
    assert result["new_checkpoint_verified"] is False
    assert [item["next_step"] for item in result["periodic_checkpoints"]] == [2]
    retention.verify_periodic(root, result, config, None)
    assert not (root / "checkpoint").exists()
    assert result["unreconciled_native_snapshot_verified"] is True
    assert (root / "unreconciled-native-save/world.sav").is_file()
    assert not (root / "unreconciled-native-save/checkpoint.json").exists()
    assert result["year_two_gameplay_verified"] is False


def test_periodic_snapshot_failure_is_a_checkpoint_failure_not_gameplay_collapse(tmp_path):
    class BrokenSnapshot:
        def capture(self, path):
            raise OSError("synthetic save failure")

    result, root, agent = segment(tmp_path, config=condition(), snapshotter=BrokenSnapshot())
    assert agent.dispatches == 2
    assert result["status"] == "checkpoint_failed"
    assert result["periodic_checkpoint_error_type"] == "OSError"
    assert result["new_checkpoint_verified"] is False
    assert (root / "checkpoints/step-000002").is_dir()


@pytest.mark.parametrize(
    "field,value",
    [
        ("interval_steps", True),
        ("interval_steps", 0),
        ("interval_steps", 33),
        ("minimum_free_bytes", True),
        ("minimum_free_bytes", 0),
        ("minimum_free_bytes", 8589934593),
        ("profile", "unknown/v1"),
    ],
)
def test_invalid_retention_policies_fail_validation(field, value):
    config = deepcopy(load_segment_config(CONFIG, MODEL))
    config["checkpoint_policy"][field] = value
    with pytest.raises(ValueError):
        validate_bounds(config, MODEL, local=True)


def test_long_local_segments_require_the_explicit_periodic_policy():
    config = load_segment_config(CONFIG, MODEL)
    assert config["segment_time_budget_seconds"] == 7200
    assert config["max_dispatches"] == 64 and config["max_steps"] == 32
    config.pop("checkpoint_policy")
    with pytest.raises(ValueError, match="segment_time_budget"):
        validate_bounds(config, MODEL, local=True)
    old = load_segment_config(CONFIG.with_name("local_native_llama_thinking_v1.json"), MODEL)
    assert old["max_dispatches"] == 8 and "checkpoint_policy" not in old


def test_partial_periodic_index_cannot_be_accepted(tmp_path):
    config = condition()
    result, root, _ = segment(tmp_path, config=config)
    path = root / "periodic-checkpoints.jsonl"
    path.write_bytes(path.read_bytes().rstrip(b"\n"))
    with pytest.raises(ValueError, match="index differs"):
        retention.verify_periodic(root, result, config, None)


def test_checkpoint_interval_cannot_exceed_segment_steps():
    config = deepcopy(load_segment_config(CONFIG, MODEL))
    config["max_steps"] = 4
    with pytest.raises(ValueError, match="interval exceeds"):
        validate_bounds(config, MODEL, local=True)
