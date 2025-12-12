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


def test_reset_current_from_seed_rejects_bad_name(tmp_path):
    from fort_gym.bench.run.seed_reset import SeedResetError, reset_current_from_seed

    with pytest.raises(SeedResetError):
        reset_current_from_seed("../bad", dfroot=tmp_path, restart_service=False)

