"""Offline receipt tests; real menu/save acceptance is a separate native run."""

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from fort_gym.bench.run.campaign_save import CampaignSaveError, NativeSaveSnapshotter
from fort_gym.bench.run.keyboard_config import load_window
from fort_gym.bench.run.keyboard_save import (
    MENU_IDENTITY_SAVE_PROFILE,
    MENU_SETTLED_IDENTITY_SAVE_PROFILE,
    LEGACY_SAVE_PROFILE,
    MENU_SAVE_PROFILE,
    MenuPreservingSnapshotter,
    validate_menu_save,
)
from fort_gym.bench.run.keyboard_save_lua import MENU_SAVE_LUA
from tests.test_campaign_save import NativeSaveSimulation


def receipt(root):
    boundary = {
        "dfroot": str(root.resolve()),
        "save_name": "region3",
        "year": 30,
        "year_tick": 200,
        "paused": True,
        "autosave_requested": False,
    }
    return {
        "schema_version": "fortgym.native-menu-save/v1",
        "ok": True,
        "native_before": boundary,
        "native_after": deepcopy(boundary),
        "menu_stack_restored": True,
        "backup_setting_restored": True,
        "gameplay_keys_sent": 0,
        "native_logic_calls_requested": 1,
        "dfhack_version": "0.47.05-r8",
        "original_stack": [
            {"type": "<type: viewscreen_unitst>", "address": "123"},
            {"type": "<type: viewscreen_dwarfmodest>", "address": "456"},
        ],
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("ok", 1),
        ("ok", False),
        ("menu_stack_restored", False),
        ("backup_setting_restored", False),
        ("gameplay_keys_sent", True),
        ("gameplay_keys_sent", 1),
        ("native_logic_calls_requested", True),
        ("native_logic_calls_requested", 2),
        ("error", "nil"),
        ("dfhack_version", ""),
        ("original_stack", []),
        ("original_stack", [None]),
        ("native_after", {}),
    ],
)
def test_invalid_receipt_is_not_a_verified_save(tmp_path, field, value):
    value_before = receipt(tmp_path)
    value_before[field] = value
    with pytest.raises(CampaignSaveError):
        validate_menu_save(value_before, tmp_path)


@pytest.mark.parametrize(
    "field,value",
    [
        ("dfroot", "/other"),
        ("year", True),
        ("year_tick", -1),
        ("paused", 1),
        ("autosave_requested", True),
        ("save_name", "../elsewhere"),
    ],
)
def test_identical_but_invalid_native_boundaries_are_rejected(tmp_path, field, value):
    result = receipt(tmp_path)
    result["native_before"][field] = result["native_after"][field] = value
    with pytest.raises(CampaignSaveError):
        validate_menu_save(result, tmp_path)


@pytest.mark.parametrize("field,value", [("paused", 1), ("autosave_requested", 0)])
def test_equal_boolean_coercion_in_after_boundary_is_rejected(tmp_path, field, value):
    result = receipt(tmp_path)
    result["native_after"][field] = value
    assert result["native_before"] == result["native_after"]
    with pytest.raises(CampaignSaveError):
        validate_menu_save(result, tmp_path)


@pytest.mark.parametrize("change", ["duplicate", "missing_ancestor", "foreign_screen"])
def test_invalid_stack_is_rejected(tmp_path, change):
    result = receipt(tmp_path)
    if change == "duplicate":
        result["original_stack"][0]["address"] = "456"
    elif change == "missing_ancestor":
        result["original_stack"].pop()
    else:
        result["original_stack"][0]["type"] = "plugin screen"
    with pytest.raises(CampaignSaveError):
        validate_menu_save(result, tmp_path)


def snapshot_fixture(tmp_path, response=None, screen_changed=False):
    native = NativeSaveSimulation(tmp_path)
    calls = []

    def execute(expression, *, timeout):
        calls.append(expression)
        assert timeout == 120 and expression.endswith(MENU_SAVE_LUA)
        native.request()
        native.status()
        native.status()
        if isinstance(response, Exception):
            raise response
        return response if response is not None else json.dumps(receipt(native.dfroot))

    snapshotter = MenuPreservingSnapshotter(
        dfroot=native.dfroot,
        execute=execute,
        status=native.status,
        screen_capture=lambda: {"tiles": [99 if calls and screen_changed else 32]},
    )
    return snapshotter, native, calls


def test_success_retains_receipt_screen_digest_and_copied_save(tmp_path):
    snapshotter, native, calls = snapshot_fixture(tmp_path)
    result = snapshotter.capture(tmp_path / "snapshot")
    assert len(calls) == native.requests == 1
    assert result["snapshot_profile"] == MENU_SAVE_PROFILE
    assert result["screen_unchanged"] is True and len(result["screen_sha256"]) == 64
    assert result["save_operation"] == receipt(native.dfroot)
    assert (tmp_path / "snapshot/world.sav").read_bytes() == b"new native save"


@pytest.mark.parametrize("response", ["bad json", "null", "{}", RuntimeError("uncertain RPC")])
def test_bad_or_uncertain_request_never_retries_or_copies(tmp_path, response):
    snapshotter, _, calls = snapshot_fixture(tmp_path, response=response)
    with pytest.raises((CampaignSaveError, RuntimeError)):
        snapshotter.capture(tmp_path / "snapshot")
    assert len(calls) == 1 and not (tmp_path / "snapshot").exists()


def test_changed_screen_leaves_forensic_copy_but_no_success_receipt(tmp_path):
    snapshotter, _, calls = snapshot_fixture(tmp_path, screen_changed=True)
    with pytest.raises(CampaignSaveError, match="screen changed"):
        snapshotter.capture(tmp_path / "snapshot")
    assert len(calls) == 1 and (tmp_path / "snapshot/world.sav").exists()
    assert snapshotter.attempt["screen_before"] == {"tiles": [32]}
    assert snapshotter.attempt["screen_after"] == {"tiles": [99]}
    assert snapshotter.attempt["save_operation"]["menu_stack_restored"] is True
    assert snapshotter.attempt["copied_native_save"]["year_tick"] == 200


def test_existing_destination_cannot_trigger_native_save(tmp_path):
    snapshotter, _, calls = snapshot_fixture(tmp_path)
    destination = tmp_path / "snapshot"
    destination.mkdir()
    with pytest.raises(CampaignSaveError, match="already exists"):
        snapshotter.capture(destination)
    assert calls == []


@pytest.mark.parametrize("profile", [None, LEGACY_SAVE_PROFILE, MENU_SAVE_PROFILE, MENU_IDENTITY_SAVE_PROFILE, MENU_SETTLED_IDENTITY_SAVE_PROFILE, "unknown"])
def test_window_profile_is_explicit_and_legacy_defaults_stay_unchanged(tmp_path, profile):
    project = Path(__file__).resolve().parents[1]
    condition = project / "experiments/campaign_astra_keyboard_20260907.json"
    source = project / "experiments/campaign_astra_keyboard_window_20260907d.json"
    window = json.loads(source.read_text())
    if profile is not None:
        window["snapshot_profile"] = profile
    target = tmp_path / "window.json"
    target.write_text(json.dumps(window))
    if profile == "unknown":
        with pytest.raises(ValueError, match="snapshot profile"):
            load_window(condition, target)
    else:
        _, loaded = load_window(condition, target)
        assert loaded.get("snapshot_profile", LEGACY_SAVE_PROFILE) == (
            profile or LEGACY_SAVE_PROFILE
        )


@pytest.mark.parametrize(
    "profile,expected",
    [
        (LEGACY_SAVE_PROFILE, NativeSaveSnapshotter),
        (MENU_SAVE_PROFILE, MenuPreservingSnapshotter),
        (MENU_IDENTITY_SAVE_PROFILE, MenuPreservingSnapshotter),
        (MENU_SETTLED_IDENTITY_SAVE_PROFILE, MenuPreservingSnapshotter),
    ],
)
def test_native_worker_selects_only_declared_snapshotter(tmp_path, monkeypatch, profile, expected):
    from scripts import campaign_keyboard_native as runtime
    from tests.test_keyboard_runtime import CONDITION, environment

    monkeypatch.setattr(
        runtime,
        "load_window",
        lambda *args: (
            CONDITION,
            {"steps_per_segment": 1, "snapshot_profile": profile},
        ),
    )
    env = environment()
    env.close = lambda: None
    monkeypatch.setattr(runtime, "NativeCampaignEnvironment", lambda **kwargs: env)
    monkeypatch.setattr(runtime, "run_keyboard_segment", lambda **kwargs: kwargs["snapshotter"])
    args = SimpleNamespace(
        condition=None,
        window=None,
        runtime=tmp_path,
        exchange=tmp_path,
        output=tmp_path,
        checkpoint=tmp_path,
        latest_usage=tmp_path,
        cursor=184,
        revision="fixture",
        extend_budget=False,
    )
    assert isinstance(runtime.worker(args), expected)
