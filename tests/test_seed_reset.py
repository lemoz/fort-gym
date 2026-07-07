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


def test_maybe_reset_honors_per_run_seed_override(monkeypatch):
    from types import SimpleNamespace

    from fort_gym.bench.run import seed_reset

    calls = []

    def fake_reset(seed_name, *, runtime_name, **kwargs):
        calls.append((seed_name, runtime_name))

    monkeypatch.setattr(seed_reset, "reset_save_from_seed", fake_reset)
    settings = SimpleNamespace(
        FORT_GYM_SEED_SAVE="seed_region1_fresh",
        FORT_GYM_RUNTIME_SAVE="region1",
        DFHACK_HOST="127.0.0.1",
        DFHACK_PORT=5000,
    )

    # default: env-configured seed
    seed_reset.maybe_reset_dfhack_seed(settings)
    # per-run override (G6): a different embark without touching env config
    seed_reset.maybe_reset_dfhack_seed(
        settings, seed_save="seed_region3_fresh", runtime_save="region3"
    )
    # override works even when the deployment has no default seed configured
    bare = SimpleNamespace(
        FORT_GYM_SEED_SAVE=None,
        FORT_GYM_RUNTIME_SAVE="current",
        DFHACK_HOST="127.0.0.1",
        DFHACK_PORT=5000,
    )
    seed_reset.maybe_reset_dfhack_seed(bare, seed_save="seed_region3_fresh")

    assert calls == [
        ("seed_region1_fresh", "region1"),
        ("seed_region3_fresh", "region3"),
        ("seed_region3_fresh", "current"),
    ]


def test_run_create_request_validates_seed_names():
    import pytest
    from pydantic import ValidationError

    from fort_gym.bench.api.schemas import RunCreateRequest

    ok = RunCreateRequest(seed_save="seed_region3_fresh", runtime_save="region3")
    assert ok.seed_save == "seed_region3_fresh"
    assert RunCreateRequest().seed_save is None

    for bad in ("../etc", "a/b", "region3;rm"):
        with pytest.raises(ValidationError):
            RunCreateRequest(seed_save=bad)
