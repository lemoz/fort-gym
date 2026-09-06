from __future__ import annotations

from copy import deepcopy

import pytest

from fort_gym.bench.run.campaign_save import (
    CampaignSaveError,
    NativeSaveSnapshotter,
    save_inventory,
)


class NativeSaveSimulation:
    """Filesystem/RPC test double, not evidence of real DF save completion."""

    def __init__(self, tmp_path):
        self.dfroot = tmp_path / "df"
        self.source = self.dfroot / "data/save/region3"
        self.source.mkdir(parents=True)
        self.world = self.source / "world.sav"
        self.world.write_bytes(b"old native save")
        self.state = {
            "ok": True,
            "save_name": "region3",
            "year": 30,
            "year_tick": 200,
            "paused": True,
            "autosave_requested": False,
        }
        self.time = 0.0
        self.requests = 0
        self.polls = 0
        self.complete = True
        self.rpc_failure = False

    def request(self):
        self.requests += 1
        self.state["autosave_requested"] = True

    def status(self):
        if self.requests:
            self.polls += 1
            if self.rpc_failure and self.polls == 1:
                raise RuntimeError("RPC temporarily unavailable while saving")
            if self.complete and self.polls >= 2:
                if self.state["autosave_requested"]:
                    self.world.write_bytes(b"new native save")
                self.state["autosave_requested"] = False
        return deepcopy(self.state)

    def sleep(self, seconds):
        self.time += seconds

    def snapshotter(self):
        return NativeSaveSnapshotter(
            dfroot=self.dfroot,
            status=self.status,
            request_save=self.request,
            clock=lambda: self.time,
            sleep=self.sleep,
            timeout_seconds=1,
        )


def test_waits_for_completed_save_and_copies_verified_files(tmp_path):
    native = NativeSaveSimulation(tmp_path)
    (native.source / "subdir").mkdir()
    (native.source / "subdir" / "region.sav").write_bytes(b"region")
    destination = tmp_path / "snapshot"
    receipt = native.snapshotter().capture(destination)
    assert native.requests == 1
    assert native.polls >= 2
    assert (destination / "world.sav").read_bytes() == b"new native save"
    assert receipt["files"] == save_inventory(native.source)
    assert receipt["year"] == 30 and receipt["year_tick"] == 200


def test_successful_command_without_completed_save_does_not_copy(tmp_path):
    native = NativeSaveSimulation(tmp_path)
    native.complete = False
    destination = tmp_path / "snapshot"
    with pytest.raises(CampaignSaveError, match="completion"):
        native.snapshotter().capture(destination)
    assert native.requests == 1
    assert not destination.exists()


def test_rpc_interruption_retries_observation_not_the_save_request(tmp_path):
    native = NativeSaveSimulation(tmp_path)
    native.rpc_failure = True
    native.snapshotter().capture(tmp_path / "snapshot")
    assert native.requests == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("paused", False),
        ("paused", 1),
        ("ok", False),
        ("save_name", "../secret"),
        ("year", True),
        ("year_tick", 403200),
        ("autosave_requested", True),
    ],
)
def test_invalid_boundary_does_not_request_a_save(tmp_path, field, value):
    native = NativeSaveSimulation(tmp_path)
    native.state[field] = value
    with pytest.raises(CampaignSaveError):
        native.snapshotter().capture(tmp_path / "snapshot")
    assert native.requests == 0


def test_existing_snapshot_is_never_overwritten(tmp_path):
    native = NativeSaveSimulation(tmp_path)
    destination = tmp_path / "snapshot"
    destination.mkdir()
    (destination / "keep").write_text("original")
    with pytest.raises(CampaignSaveError, match="already exists"):
        native.snapshotter().capture(destination)
    assert (destination / "keep").read_text() == "original"
    assert native.requests == 0


def test_game_time_advancing_during_save_is_not_a_matching_checkpoint(tmp_path):
    native = NativeSaveSimulation(tmp_path)
    original = native.status

    def drift():
        state = original()
        if native.requests:
            state["year_tick"] += 1
        return state

    snapshotter = native.snapshotter()
    snapshotter.status = drift
    with pytest.raises(CampaignSaveError, match="changed"):
        snapshotter.capture(tmp_path / "snapshot")


def test_save_file_does_not_update_even_if_request_flag_clears(tmp_path):
    native = NativeSaveSimulation(tmp_path)
    snapshotter = native.snapshotter()
    snapshotter.request_save = lambda: None
    with pytest.raises(CampaignSaveError, match="completion"):
        snapshotter.capture(tmp_path / "snapshot")


def test_inventory_rejects_symlinks_and_empty_saves(tmp_path):
    native = NativeSaveSimulation(tmp_path)
    (native.source / "outside").symlink_to(tmp_path / "unrelated")
    with pytest.raises(CampaignSaveError, match="symbolic"):
        save_inventory(native.source)
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(CampaignSaveError, match="world.sav"):
        save_inventory(empty)


def test_snapshot_must_not_be_inside_live_save(tmp_path):
    native = NativeSaveSimulation(tmp_path)
    with pytest.raises(CampaignSaveError, match="outside"):
        native.snapshotter().capture(native.source / "nested")
    assert native.requests == 0


def test_source_mutation_during_copy_is_rejected(tmp_path, monkeypatch):
    from fort_gym.bench.run import campaign_save

    native = NativeSaveSimulation(tmp_path)
    copytree = campaign_save.shutil.copytree

    def mutate(source, destination, **kwargs):
        result = copytree(source, destination, **kwargs)
        native.world.write_bytes(b"changed after copy")
        return result

    monkeypatch.setattr(campaign_save.shutil, "copytree", mutate)
    with pytest.raises(CampaignSaveError, match="changed"):
        native.snapshotter().capture(tmp_path / "snapshot")
