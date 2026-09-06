"""Copy-space estimates must precede native allocation, not follow it."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import campaign_load_smoke as module
from tests import test_campaign_load_smoke as fixtures

sources = fixtures.sources


def capacity(sources, tmp_path, **kwargs):
    source, snapshot, _ = sources
    return module.runtime_capacity(source, snapshot / "native-snapshot", tmp_path, **kwargs)


def test_current_free_above_floor_is_insufficient_after_copy(sources, tmp_path, monkeypatch):
    report = capacity(sources, tmp_path, minimum_free_bytes=1000000, checkpoint_copies=4)
    free = 1000000 + report["estimated_copy_bytes"] - 1
    monkeypatch.setattr(module.shutil, "disk_usage", lambda path: SimpleNamespace(free=free))
    assert free > 1000000
    report = capacity(sources, tmp_path, minimum_free_bytes=1000000, checkpoint_copies=4)
    assert report["fits"] is False
    assert report["estimated_free_after_copy_bytes"] == 999999
    assert report["space_reserved"] is False and report["future_growth_included"] is False
    source, snapshot, _ = sources
    with pytest.raises(module.CampaignSaveError, match="copies would cross"):
        module.require_runtime_capacity(
            source,
            snapshot / "native-snapshot",
            tmp_path,
            minimum_free_bytes=1000000,
            checkpoint_copies=4,
        )


def test_checkpoint_estimate_counts_each_retained_save(sources, tmp_path):
    baseline = capacity(sources, tmp_path)
    retained = capacity(sources, tmp_path, checkpoint_copies=4)
    assert retained["estimated_copy_bytes"] - baseline["estimated_copy_bytes"] == (
        4 * retained["estimated_starting_save_bytes"]
    )
    assert retained["additional_checkpoint_copies"] == 4


def test_only_selected_runtime_files_and_current_snapshot_count(sources, tmp_path):
    source, snapshot, _ = sources
    first = capacity(sources, tmp_path)
    (source / "stdout.log").write_bytes(b"x" * 100000)
    (source / "data/save/original/world.sav").write_bytes(b"x" * 100000)
    for name in ("seed_saves", "save_backups", "save-quarantine"):
        archive = source / "data" / name
        archive.mkdir()
        (archive / "retained-world.sav").write_bytes(b"x" * 100000)
    second = capacity(sources, tmp_path)
    assert first["estimated_copy_bytes"] == second["estimated_copy_bytes"]
    (snapshot / "native-snapshot/world.sav").write_bytes(b"x" * 100000)
    assert capacity(sources, tmp_path)["estimated_copy_bytes"] > second["estimated_copy_bytes"]


def test_hook_override_is_measured_instead_of_old_runtime_hooks(sources, tmp_path):
    source, _, _ = sources
    (source / "hook").mkdir()
    (source / "hook/old.lua").write_bytes(b"x" * 100000)
    hooks = tmp_path / "new-hooks"
    hooks.mkdir()
    (hooks / "new.lua").write_text("return true")
    old = capacity(sources, tmp_path)
    new = capacity(sources, tmp_path, hook_source=hooks)
    assert new["estimated_runtime_asset_bytes"] < old["estimated_runtime_asset_bytes"]


def test_followed_links_count_per_copy_and_cycles_fail(sources, tmp_path):
    source, _, _ = sources
    libs = source / "libs"
    libs.mkdir()
    target = libs / "real.so"
    target.write_bytes(b"x" * 20000)
    first = capacity(sources, tmp_path)
    (libs / "linked.so").symlink_to(target.name)
    linked = capacity(sources, tmp_path)
    assert linked["estimated_runtime_asset_bytes"] > first["estimated_runtime_asset_bytes"]
    (libs / "cycle").symlink_to(libs, target_is_directory=True)
    with pytest.raises(module.CampaignSaveError, match="link cycle"):
        capacity(sources, tmp_path)


@pytest.mark.parametrize(
    "field,value",
    [
        ("minimum_free_bytes", -1),
        ("minimum_free_bytes", True),
        ("checkpoint_copies", -1),
        ("checkpoint_copies", True),
        ("checkpoint_copies", 33),
    ],
)
def test_invalid_capacity_parameters_rejected(sources, tmp_path, field, value):
    with pytest.raises(module.CampaignSaveError):
        capacity(sources, tmp_path, **{field: value})


def test_shortage_rejected_before_any_native_output_or_process(sources, tmp_path, monkeypatch):
    source, snapshot, digest = sources
    monkeypatch.setattr(module.shutil, "disk_usage", lambda path: SimpleNamespace(free=1))
    monkeypatch.setattr(module.socket, "socket", lambda: pytest.fail("Must not allocate listener"))
    monkeypatch.setattr(
        module.subprocess, "Popen", lambda *a, **kw: pytest.fail("Must not start game")
    )
    output = tmp_path / "new-run"
    with pytest.raises(module.CampaignSaveError, match="copies would cross"):
        module.run_isolated(
            source=source,
            snapshot=snapshot,
            digest=digest,
            output=output,
            port=5501,
            revision="test-only",
            work=lambda *args: pytest.fail("Must not infer"),
        )
    assert not output.exists()


def test_new_runtime_omits_archives_but_preserves_every_source_copy(sources, tmp_path):
    source, snapshot, _ = sources
    names = ("seed_saves", "save_backups", "save-quarantine")
    for name in names:
        archive = source / "data" / name
        archive.mkdir()
        (archive / "historical-world.sav").write_bytes(name.encode())
    output = tmp_path / "runtime"
    module.prepare_runtime(source, output, snapshot / "native-snapshot", port=5501)
    for name in names:
        assert not (output / "data" / name).exists()
        assert (source / "data" / name / "historical-world.sav").read_bytes() == name.encode()
    assert (source / "data/save/original/world.sav").read_bytes() == b"original fortress"
    assert (output / "data/save/campaign-resume/world.sav").read_bytes() == b"saved fortress"


def test_prepare_rechecks_capacity_before_copying(sources, tmp_path, monkeypatch):
    source, snapshot, _ = sources
    monkeypatch.setattr(module.shutil, "disk_usage", lambda path: SimpleNamespace(free=1))
    output = tmp_path / "new-runtime"
    with pytest.raises(module.CampaignSaveError, match="copies would cross"):
        module.prepare_runtime(source, output, snapshot / "native-snapshot", port=5501)
    assert not output.exists()


def test_segment_rejects_copy_shortage_before_model_or_public_feed(sources, tmp_path, monkeypatch):
    from scripts import campaign_development, campaign_segment

    source, snapshot, digest = sources
    root = Path(__file__).resolve().parents[1]
    config_path = root / "experiments/campaigns/local_native_llama_long_v2.json"
    model = "fort-gym-qwen35-9b-q4-03b74727a860"
    config = campaign_segment.load_segment_config(config_path, model)
    floor = config["checkpoint_policy"]["minimum_free_bytes"]
    copies = 1 + (config["max_steps"] - 1) // config["checkpoint_policy"]["interval_steps"]
    report = capacity(sources, tmp_path, hook_source=root / "hook", checkpoint_copies=copies)
    monkeypatch.setattr(
        module.shutil,
        "disk_usage",
        lambda path: SimpleNamespace(free=floor + report["estimated_copy_bytes"] - 1),
    )
    monkeypatch.setattr(
        campaign_segment.subprocess,
        "check_output",
        lambda command, **kwargs: "a" * 40 if command[1] == "rev-parse" else b"",
    )
    monkeypatch.setattr(
        campaign_development,
        "verify_local_transport",
        lambda *args: pytest.fail("Capacity must be checked before contacting the model service"),
    )
    args = SimpleNamespace(
        source=source,
        snapshot=snapshot,
        snapshot_sha256=digest,
        checkpoint=None,
        output=tmp_path / "new-run",
        model=model,
        local_endpoint="http://127.0.0.1:19001",
        public_campaign_dir=tmp_path / "public",
    )
    with pytest.raises(module.CampaignSaveError, match="copies would cross"):
        campaign_segment.launch_segment(args, config)
    assert not args.output.exists() and not args.public_campaign_dir.exists()
