from __future__ import annotations

import json
from copy import deepcopy

import pytest

from fort_gym.bench.agent.base import Agent
from fort_gym.bench.run.campaign_checkpoint import (
    CampaignCheckpointError,
    create_checkpoint,
    materialize_checkpoint,
    verify_checkpoint,
)
from fort_gym.bench.run.campaign_save import NativeSaveSnapshotter


class CheckpointAgent(Agent):
    def __init__(self):
        self.state = {"campaign_id": "fort-1", "memory": {"plan": "brew"}}

    def decide(self, obs_text, obs_json):
        raise AssertionError("Checkpoint operations must not make gameplay decisions")

    def export_campaign_state(self):
        return deepcopy(self.state)


@pytest.fixture
def campaign(tmp_path):
    dfroot = tmp_path / "df"
    world = dfroot / "data/save/region3/world.sav"
    world.parent.mkdir(parents=True)
    world.write_bytes(b"initial")
    status = {
        "ok": True,
        "save_name": "region3",
        "year": 30,
        "year_tick": 200,
        "paused": True,
        "autosave_requested": False,
    }
    trace = tmp_path / "trace.jsonl"
    trace.write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "step": 0,
                "tick_advance": {"end_year": 30, "end_tick": 200, "ticks_advanced": 100},
            }
        )
        + "\n"
    )
    snapshotter = NativeSaveSnapshotter(
        dfroot=dfroot,
        status=lambda: deepcopy(status),
        request_save=lambda: world.write_bytes(b"saved-current-world"),
    )
    return {
        "campaign_id": "fort-1",
        "agent": CheckpointAgent(),
        "snapshotter": snapshotter,
        "trace_path": trace,
        "last_committed_step": 0,
        "code_revision": "test-only",
    }


def test_checkpoint_binds_save_agent_and_trace_and_materializes_new_runtime(tmp_path, campaign):
    directory = tmp_path / "checkpoint"
    manifest = create_checkpoint(directory, **campaign)
    assert verify_checkpoint(directory) == manifest
    restored = materialize_checkpoint(directory, save_destination=tmp_path / "new-runtime-save")
    assert restored["agent_state"] == campaign["agent"].state
    assert restored["next_step"] == 1
    assert restored["runtime_loaded"] is False
    assert (tmp_path / "new-runtime-save/world.sav").read_bytes() == b"saved-current-world"


@pytest.mark.parametrize("name", ["game/world.sav", "agent.json", "trace.jsonl", "checkpoint.json"])
def test_modified_checkpoint_is_not_restored(tmp_path, campaign, name):
    directory = tmp_path / "checkpoint"
    create_checkpoint(directory, **campaign)
    (directory / name).write_text("{}")
    destination = tmp_path / "restore"
    with pytest.raises((CampaignCheckpointError, RuntimeError)):
        materialize_checkpoint(directory, save_destination=destination)
    assert not destination.exists()


def test_wrong_trace_cursor_fails_before_save_or_directory_creation(tmp_path, campaign):
    campaign["last_committed_step"] = 3
    destination = tmp_path / "checkpoint"
    with pytest.raises(CampaignCheckpointError, match="cursor"):
        create_checkpoint(destination, **campaign)
    assert not destination.exists()


def test_changed_agent_during_save_leaves_no_final_manifest(tmp_path, campaign):
    original = campaign["snapshotter"].request_save

    def change():
        original()
        campaign["agent"].state["memory"]["plan"] = "changed"

    campaign["snapshotter"].request_save = change
    destination = tmp_path / "checkpoint"
    with pytest.raises(CampaignCheckpointError, match="changed"):
        create_checkpoint(destination, **campaign)
    assert not (destination / "checkpoint.json").exists()


def test_partial_trace_line_is_not_a_commit_boundary(tmp_path, campaign):
    trace = campaign["trace_path"]
    trace.write_bytes(trace.read_bytes().rstrip(b"\n"))
    with pytest.raises(CampaignCheckpointError, match="newline"):
        create_checkpoint(tmp_path / "checkpoint", **campaign)


def test_existing_runtime_save_is_not_replaced(tmp_path, campaign):
    directory = tmp_path / "checkpoint"
    create_checkpoint(directory, **campaign)
    destination = tmp_path / "runtime"
    destination.mkdir()
    (destination / "world.sav").write_bytes(b"keep this fortress")
    with pytest.raises(CampaignCheckpointError, match="overwrite"):
        materialize_checkpoint(directory, save_destination=destination)
    assert (destination / "world.sav").read_bytes() == b"keep this fortress"


def test_parent_checkpoint_is_bound_to_same_campaign(tmp_path, campaign):
    parent = tmp_path / "parent"
    first = create_checkpoint(parent, **campaign)
    second = create_checkpoint(tmp_path / "second", parent=parent, **campaign)
    assert second["payload"]["parent_sha256"] == first["sha256"]
    campaign["agent"].state["campaign_id"] = "other"
    campaign["campaign_id"] = "other"
    with pytest.raises(CampaignCheckpointError, match="Parent"):
        create_checkpoint(tmp_path / "third", parent=parent, **campaign)


def test_native_save_must_match_trace_calendar(tmp_path, campaign):
    trace = campaign["trace_path"]
    row = json.loads(trace.read_text())
    row["tick_advance"]["end_tick"] = 123
    trace.write_text(json.dumps(row) + "\n")
    with pytest.raises(CampaignCheckpointError, match="calendar"):
        create_checkpoint(tmp_path / "checkpoint", **campaign)
    assert not (tmp_path / "checkpoint/checkpoint.json").exists()
