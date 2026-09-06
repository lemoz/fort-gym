from __future__ import annotations

import hashlib
import json

import pytest

from fort_gym.bench.run.campaign_save import CampaignSaveError, save_inventory
from scripts import campaign_load_smoke as smoke


@pytest.fixture
def sources(tmp_path):
    source = tmp_path / "source"
    (source / "data/init").mkdir(parents=True)
    (source / "data/init/d_init.txt").write_text("[PAUSE_ON_LOAD:YES]\n")
    (source / "data/save/original").mkdir(parents=True)
    (source / "data/save/original/world.sav").write_bytes(b"original fortress")
    (source / "dfhack-config").mkdir()
    (source / "dfhack-config/remote-server.json").write_text('{"port":5000}\n')
    for name in smoke.RUNTIME_FILES:
        (source / name).write_text("fixture, not executable game code")
    (source / "stdout.log").write_bytes(b"large log excluded")
    snapshot = tmp_path / "snapshot"
    (snapshot / "native-snapshot").mkdir(parents=True)
    (snapshot / "native-snapshot/world.sav").write_bytes(b"saved fortress")
    boundary = {"year": 30, "year_tick": 19309, "paused": True, "save_name": "region3"}
    receipt = {
        "schema_version": "fortgym.native-save-smoke/v1",
        "native_snapshot_verified": True,
        "before": boundary,
        "after": boundary,
        "snapshot": {"files": save_inventory(snapshot / "native-snapshot")},
    }
    data = json.dumps(receipt).encode()
    (snapshot / "result.json").write_bytes(data)
    return source, snapshot, hashlib.sha256(data).hexdigest()


def test_prepare_copies_only_selected_runtime_and_snapshot(tmp_path, sources):
    source, snapshot, _ = sources
    destination = tmp_path / "isolated"
    smoke.prepare_runtime(source, destination, snapshot / "native-snapshot", port=5501)
    assert not (destination / "stdout.log").exists()
    assert not (destination / "data/save/original").exists()
    assert save_inventory(destination / "data/save/campaign-resume") == save_inventory(
        snapshot / "native-snapshot"
    )
    assert json.loads((destination / "dfhack-config/remote-server.json").read_text()) == {
        "allow_remote": False,
        "port": 5501,
    }
    assert json.loads((source / "dfhack-config/remote-server.json").read_text()) == {"port": 5000}


@pytest.mark.parametrize("port", [0, 80, 5000, 65536])
def test_prepare_rejects_invalid_or_production_port(tmp_path, sources, port):
    source, snapshot, _ = sources
    with pytest.raises(CampaignSaveError, match="port"):
        smoke.prepare_runtime(
            source, tmp_path / "isolated", snapshot / "native-snapshot", port=port
        )
    assert not (tmp_path / "isolated").exists()


def test_prepare_never_overwrites_or_nests_in_source(tmp_path, sources):
    source, snapshot, _ = sources
    with pytest.raises(CampaignSaveError, match="outside"):
        smoke.prepare_runtime(source, source / "nested", snapshot / "native-snapshot", port=5501)
    with pytest.raises(CampaignSaveError, match="exists"):
        smoke.prepare_runtime(source, snapshot, snapshot / "native-snapshot", port=5501)


def test_prepare_requires_existing_pause_on_load(tmp_path, sources):
    source, snapshot, _ = sources
    (source / "data/init/d_init.txt").write_text("[PAUSE_ON_LOAD:NO]\n")
    with pytest.raises(CampaignSaveError, match="pause on load"):
        smoke.prepare_runtime(
            source, tmp_path / "isolated", snapshot / "native-snapshot", port=5501
        )


def test_receipt_digest_and_save_bytes_both_verified(sources):
    _, snapshot, digest = sources
    assert smoke.verify_snapshot(snapshot, digest)["native_snapshot_verified"] is True
    with pytest.raises(CampaignSaveError, match="digest"):
        smoke.verify_snapshot(snapshot, "0" * 64)
    (snapshot / "native-snapshot/world.sav").write_bytes(b"changed")
    with pytest.raises(CampaignSaveError, match="inconsistent"):
        smoke.verify_snapshot(snapshot, digest)


def test_runtime_environment_does_not_inherit_credentials(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-only-placeholder")
    monkeypatch.setenv("LD_PRELOAD", "not-inherited")
    monkeypatch.setenv("FORT_GYM_DB_PATH", "production.sqlite")
    environment = smoke.runtime_environment(5501)
    assert not {"OPENROUTER_API_KEY", "LD_PRELOAD", "FORT_GYM_DB_PATH"} & environment.keys()
    assert environment["DFHACK_PORT"] == "5501"


def test_wrong_runtime_identity_is_rejected_before_load(tmp_path, monkeypatch):
    monkeypatch.setattr(smoke, "rpc", lambda *args: json.dumps({"dfroot": "/opt/dwarf-fortress"}))
    with pytest.raises(CampaignSaveError, match="different runtime"):
        smoke.read_status(tmp_path / "isolated", {})


@pytest.mark.parametrize("tick", [19309, 19310])
def test_load_checks_calendar_and_always_tears_down(tmp_path, sources, monkeypatch, tick):
    source, snapshot, digest = sources
    commands, kills = [], []

    class Process:
        pid = 999999

        def wait(self, timeout):
            return 0

    class Socket:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def bind(self, address):
            pass

        def connect_ex(self, address):
            return 111

    monkeypatch.setattr(smoke.subprocess, "Popen", lambda *args, **kwargs: Process())
    monkeypatch.setattr(smoke.socket, "socket", Socket)
    monkeypatch.setattr(smoke.os, "killpg", lambda pid, sig: kills.append(pid))
    monkeypatch.setattr(smoke, "group_live_members", lambda group: [])
    monkeypatch.setattr(smoke, "rpc", lambda runtime, environment, *args: commands.append(args))
    monkeypatch.setattr(
        smoke,
        "wait_status",
        lambda *args, loaded, **kwargs: {
            "map_loaded": loaded,
            "paused": True,
            "save_name": "campaign-resume" if loaded else "",
            "year": 30,
            "year_tick": tick,
        },
    )
    options = dict(
        source=source,
        snapshot=snapshot,
        digest=digest,
        output=tmp_path / "output",
        port=5501,
        revision="test-source",
    )
    if tick == 19309:
        result = smoke.run_smoke(**options)
        assert result["native_load_verified"] is True
        assert result["campaign_recovery_verified"] is False
    else:
        with pytest.raises(CampaignSaveError, match="calendar"):
            smoke.run_smoke(**options)
    result = json.loads((tmp_path / "output/result.json").read_text())
    assert result["cleanup_verified"] is True
    assert result["native_load_verified"] is (tick == 19309)
    assert commands == [("load-save", "campaign-resume")]
    assert kills == [999999]


def test_no_output_inside_retained_snapshot(sources):
    source, snapshot, digest = sources
    with pytest.raises(CampaignSaveError, match="outside"):
        smoke.run_smoke(
            source=source,
            snapshot=snapshot,
            digest=digest,
            output=snapshot / "nested",
            port=5501,
            revision="test-source",
        )
    assert not (snapshot / "nested").exists()
