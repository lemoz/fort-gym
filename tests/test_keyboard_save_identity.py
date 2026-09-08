import json
from copy import deepcopy

import pytest

from fort_gym.bench.run.campaign_save import CampaignSaveError
from fort_gym.bench.run.keyboard_save import MENU_IDENTITY_SAVE_PROFILE, MenuPreservingSnapshotter, validate_menu_save
from fort_gym.bench.run.keyboard_save_lua import MENU_IDENTITY_SAVE_LUA
from tests.test_campaign_save import NativeSaveSimulation
from tests.test_keyboard_save import receipt


def semantic_receipt(root):
    value = receipt(root)
    value["schema_version"] = "fortgym.native-menu-save/v2"
    ui = {"focus": "dwarfmode/Default", "unit_id": -1, "building_id": -1, "job_id": -1,
          "item_id": -1, "cursor": {"x": -30000, "y": -30000, "z": -30000},
          "viewport": {"x": 0, "y": 0, "z": 120}}
    value["ui_before"], value["ui_after"] = ui, deepcopy(ui)
    return value


@pytest.mark.parametrize("key,value", [("focus", "other"), ("unit_id", 2), ("item_id", True),
                                      ("cursor", {"x": 1, "y": 1, "z": 1})])
def test_changed_semantic_menu_identity_is_rejected(tmp_path, key, value):
    source = semantic_receipt(tmp_path)
    source["ui_after"][key] = value
    with pytest.raises(CampaignSaveError):
        validate_menu_save(source, tmp_path, profile=MENU_IDENTITY_SAVE_PROFILE)


@pytest.mark.parametrize("world_changed", [False, True])
def test_pixel_animation_is_telemetry_but_world_mutation_still_fails(tmp_path, world_changed):
    native = NativeSaveSimulation(tmp_path)
    calls = []

    def execute(expression, *, timeout):
        assert expression.endswith(MENU_IDENTITY_SAVE_LUA) and timeout == 120
        calls.append(expression)
        native.request()
        native.status()
        native.status()
        return json.dumps(semantic_receipt(native.dfroot))

    snapshotter = MenuPreservingSnapshotter(
        dfroot=native.dfroot, profile=MENU_IDENTITY_SAVE_PROFILE, execute=execute, status=native.status,
        screen_capture=lambda: {"width": 1, "height": 1, "tiles": [[99 if calls else 32, 7, 0]]},
        observe=lambda: {"population": 8 if calls and world_changed else 7},
    )
    if world_changed:
        with pytest.raises(CampaignSaveError, match="world observations"):
            snapshotter.capture(tmp_path / "snapshot")
    else:
        result = snapshotter.capture(tmp_path / "snapshot")
        assert result["screen_unchanged"] is False
        assert result["screen_sha256"] != result["screen_after_sha256"]
        assert result["world_observations_unchanged"] is result["ui_identity_unchanged"] is True
    assert len(calls) == 1


def test_semantic_save_requires_explicit_world_observer(tmp_path):
    with pytest.raises(ValueError, match="world observations"):
        MenuPreservingSnapshotter(dfroot=tmp_path, profile=MENU_IDENTITY_SAVE_PROFILE, screen_capture=lambda: {})
