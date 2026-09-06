from __future__ import annotations

import sqlite3

import pytest

from fort_gym.bench.run.campaign_save import CampaignSaveError
from scripts.campaign_save_smoke import require_idle_registry, run_smoke
from tests.test_campaign_save import NativeSaveSimulation


def registry_at(path, status=None):
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE runs (status TEXT)")
        if status is not None:
            connection.execute("INSERT INTO runs VALUES (?)", (status,))
    return path


def test_native_smoke_preserves_old_save_without_claiming_recovery(tmp_path):
    native = NativeSaveSimulation(tmp_path)
    result = run_smoke(
        output=tmp_path / "result",
        registry=registry_at(tmp_path / "registry.sqlite"),
        snapshotter=native.snapshotter(),
        code_revision="test-source",
    )
    assert (tmp_path / "result/before-save/world.sav").read_bytes() == b"old native save"
    assert (tmp_path / "result/native-snapshot/world.sav").read_bytes() == b"new native save"
    assert result["native_snapshot_verified"] is True
    assert result["campaign_recovery_verified"] is False
    assert result["provider_calls"] == 0
    assert native.requests == 1


@pytest.mark.parametrize("status", ["running", "queued", "starting", "unknown"])
def test_native_smoke_does_not_save_with_nonterminal_run(tmp_path, status):
    native = NativeSaveSimulation(tmp_path)
    with pytest.raises(CampaignSaveError, match="idle"):
        run_smoke(
            output=tmp_path / "result",
            registry=registry_at(tmp_path / "registry.sqlite", status),
            snapshotter=native.snapshotter(),
            code_revision="test-source",
        )
    assert native.requests == 0
    assert not (tmp_path / "result").exists()


@pytest.mark.parametrize("status", ["completed", "failed", "stopped"])
def test_terminal_runs_do_not_block_idle_probe(tmp_path, status):
    require_idle_registry(registry_at(tmp_path / "registry.sqlite", status))


def test_missing_registry_is_not_created(tmp_path):
    path = tmp_path / "missing.sqlite"
    with pytest.raises(sqlite3.OperationalError):
        require_idle_registry(path)
    assert not path.exists()
