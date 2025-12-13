from __future__ import annotations

import os

import pytest


def test_reset_current_from_seed_copies_and_makes_writable(tmp_path):
    from fort_gym.bench.run.seed_reset import reset_current_from_seed

    dfroot = tmp_path / "df"
    saves_dir = dfroot / "data" / "save"
    seed_dir = saves_dir / "seed_region2_fresh"
    seed_dir.mkdir(parents=True)
    seed_file = seed_dir / "foo.txt"
    seed_file.write_text("hi", encoding="utf-8")
    seed_file.chmod(0o444)

    reset_current_from_seed("seed_region2_fresh", dfroot=dfroot, restart_service=False)

    current_file = saves_dir / "current" / "foo.txt"
    assert current_file.read_text(encoding="utf-8") == "hi"
    assert os.access(current_file, os.W_OK)


def test_reset_current_from_seed_prefers_seed_saves_dir(tmp_path):
    from fort_gym.bench.run.seed_reset import reset_current_from_seed

    dfroot = tmp_path / "df"
    seed_dir = dfroot / "data" / "seed_saves" / "seed_region2_fresh"
    seed_dir.mkdir(parents=True)
    (seed_dir / "foo.txt").write_text("hi", encoding="utf-8")

    reset_current_from_seed("seed_region2_fresh", dfroot=dfroot, restart_service=False)

    current_file = dfroot / "data" / "save" / "current" / "foo.txt"
    assert current_file.read_text(encoding="utf-8") == "hi"


def test_reset_save_from_seed_supports_custom_runtime_save(tmp_path):
    from fort_gym.bench.run.seed_reset import SeedResetError, reset_save_from_seed

    dfroot = tmp_path / "df"
    saves_dir = dfroot / "data" / "save"
    seed_dir = saves_dir / "seed_region2_fresh"
    seed_dir.mkdir(parents=True)
    (seed_dir / "foo.txt").write_text("hi", encoding="utf-8")

    reset_save_from_seed(
        "seed_region2_fresh",
        runtime_name="fort_gym_current",
        dfroot=dfroot,
        restart_service=False,
    )

    assert (saves_dir / "fort_gym_current" / "foo.txt").read_text(encoding="utf-8") == "hi"

    with pytest.raises(SeedResetError):
        reset_save_from_seed(
            "seed_region2_fresh",
            runtime_name="../bad",
            dfroot=dfroot,
            restart_service=False,
        )


def test_reset_current_from_seed_rejects_bad_name(tmp_path):
    from fort_gym.bench.run.seed_reset import SeedResetError, reset_current_from_seed

    with pytest.raises(SeedResetError):
        reset_current_from_seed("../bad", dfroot=tmp_path, restart_service=False)


def test_reset_current_from_seed_handles_permission_error(monkeypatch, tmp_path):
    from fort_gym.bench.run import seed_reset

    dfroot = tmp_path / "df"
    saves_dir = dfroot / "data" / "save"
    seed_dir = dfroot / "data" / "seed_saves" / "seed_region2_fresh"
    seed_dir.mkdir(parents=True)
    (seed_dir / "foo.txt").write_text("hi", encoding="utf-8")

    # Simulate permissions preventing Path.is_dir() from stat'ing the seed.
    monkeypatch.setattr(type(seed_dir), "is_dir", lambda _self: (_ for _ in ()).throw(PermissionError()))
    monkeypatch.setattr(seed_reset, "_sudo_is_dir", lambda _p: True)
    monkeypatch.setattr(seed_reset, "_make_writable", lambda _p: None)

    seed_reset.reset_current_from_seed("seed_region2_fresh", dfroot=dfroot, restart_service=False)
    assert (saves_dir / "current" / "foo.txt").read_text(encoding="utf-8") == "hi"
