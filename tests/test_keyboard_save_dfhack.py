"""Offline regressions for identified DFHack overlays, not native acceptance."""
import json
from copy import deepcopy

import pytest

from fort_gym.bench.run.campaign_save import CampaignSaveError
from fort_gym.bench.run.keyboard_save import (
    MENU_DFHACK_IDENTITY_SAVE_PROFILE, MENU_SETTLED_IDENTITY_SAVE_PROFILE,
    MenuPreservingSnapshotter, validate_menu_save,
)
from fort_gym.bench.run.keyboard_save_lua import MENU_DFHACK_IDENTITY_SAVE_LUA
from fort_gym.bench.run.keyboard_save_probe import IDENTIFIED_MENU_PROBE_LUA
from fort_gym.bench.run.keyboard_save_screens import validate_identified_stack
from tests.test_campaign_save import NativeSaveSimulation
from tests.test_keyboard_save_settled_identity import settled_receipt


def identified_receipt(root):
    value = settled_receipt(root)
    value["schema_version"] = "fortgym.native-menu-save/v4"
    stack = [
        {"type": "<type: viewscreen_petst>", "address": "100", "kind": "native",
         "focus": "pets", "dismissed": False},
        {"type": "<type: viewscreen>", "address": "200", "kind": "dfhack",
         "focus": "dfhack/lua/status_overlay", "dismissed": False},
        {"type": "<type: viewscreen_overallstatusst>", "address": "300", "kind": "native",
         "focus": "overallstatus", "dismissed": False},
        {"type": "<type: viewscreen_dwarfmodest>", "address": "400", "kind": "native",
         "focus": "dwarfmode/Default", "dismissed": False},
    ]
    value["original_stack"] = stack
    value["ui_before"]["focus"] = value["ui_after"]["focus"] = "pets"
    for name in ("identity_before", "identity_after"):
        value[name]["schema_version"] = "fortgym.native-menu-identity/v2"
        value[name]["stack"] = deepcopy(stack)
        value[name]["ui"] = deepcopy(value["ui_before"])
    return value


def validate(value, root):
    return validate_menu_save(value, root, profile=MENU_DFHACK_IDENTITY_SAVE_PROFILE)


def test_v4_accepts_identified_overlay_but_v3_remains_native_only(tmp_path):
    value = identified_receipt(tmp_path)
    assert validate(value, tmp_path) == value
    value["schema_version"] = "fortgym.native-menu-save/v3"
    with pytest.raises(CampaignSaveError):
        validate_menu_save(value, tmp_path, profile=MENU_SETTLED_IDENTITY_SAVE_PROFILE)


@pytest.mark.parametrize("field,change", [
    ("type", "<type: viewscreen_unknown>"),
    ("type", "<type: viewscreen_unitst>"),
    ("kind", "native"), ("kind", "unknown"),
    ("focus", "unknown"), ("focus", ""), ("focus", "dfhack/"),
    ("focus", 2), ("dismissed", True), ("dismissed", 0),
    ("address", ""), ("address", "100"), ("address", 20),
    ("extra", False),
])
def test_unidentified_overlay_never_passes_even_with_matching_witnesses(tmp_path, field, change):
    value = identified_receipt(tmp_path)
    for stack in (value["original_stack"], value["identity_before"]["stack"],
                  value["identity_after"]["stack"]):
        stack[1][field] = change
    with pytest.raises(CampaignSaveError):
        validate(value, tmp_path)


@pytest.mark.parametrize("witness", ["identity_before", "identity_after"])
@pytest.mark.parametrize("field,change", [
    ("focus", "dfhack/lua/another_overlay"), ("address", "900"),
    ("dismissed", True), ("kind", "native"),
])
def test_parent_overlay_changes_are_bound_not_just_the_top_screen(tmp_path, witness, field, change):
    value = identified_receipt(tmp_path)
    value[witness]["stack"][1][field] = change
    with pytest.raises(CampaignSaveError):
        validate(value, tmp_path)


@pytest.mark.parametrize("change", ["no_fortress", "fortress_in_middle", "too_deep", "null"])
def test_stack_structure_remains_bounded(tmp_path, change):
    stack = identified_receipt(tmp_path)["original_stack"]
    if change == "no_fortress":
        stack.pop()
    elif change == "fortress_in_middle":
        stack.insert(0, {**stack[-1], "address": "999"})
    elif change == "too_deep":
        stack = [{**stack[0], "address": str(i)} for i in range(33)] + [stack[-1]]
    else:
        stack[1] = None
    with pytest.raises(CampaignSaveError):
        validate_identified_stack(stack)


@pytest.mark.parametrize("failure", [None, "unidentified_before", "changed_after", "world", "operation"])
def test_v4_three_rpc_capture_and_no_retry(tmp_path, failure):
    native = NativeSaveSimulation(tmp_path)
    source = identified_receipt(native.dfroot)
    calls = []
    if failure == "unidentified_before":
        source["identity_before"]["stack"][1]["focus"] = "unidentified"
    if failure == "changed_after":
        source["identity_after"]["stack"][1]["focus"] = "dfhack/changed"

    def execute(expression, *, timeout):
        phase = ["before", "operation", "after"][len(calls)]
        calls.append(phase)
        if phase == "operation":
            assert expression.endswith(MENU_DFHACK_IDENTITY_SAVE_LUA) and timeout == 120
            if failure == "operation":
                raise RuntimeError("Uncertain save RPC")
            native.request()
            native.status()
            native.status()
            return json.dumps({key: item for key, item in source.items()
                               if key not in ("identity_before", "identity_after")})
        assert expression.endswith(IDENTIFIED_MENU_PROBE_LUA) and timeout == 5
        return json.dumps(source["identity_" + phase])

    snapshotter = MenuPreservingSnapshotter(
        dfroot=native.dfroot, profile=MENU_DFHACK_IDENTITY_SAVE_PROFILE,
        execute=execute, status=native.status,
        screen_capture=lambda: {"width": 1, "height": 1, "tiles": [[32, 7, 0]]},
        observe=lambda: {"population": 8 if native.requests and failure == "world" else 7},
    )
    if failure:
        with pytest.raises((CampaignSaveError, RuntimeError)):
            snapshotter.capture(tmp_path / "snapshot")
    else:
        saved = snapshotter.capture(tmp_path / "snapshot")
        assert saved["snapshot_profile"] == MENU_DFHACK_IDENTITY_SAVE_PROFILE
        assert saved["save_operation"] == source
        assert saved["world_observations_unchanged"] is saved["ui_identity_unchanged"] is True
    assert calls == (["before"] if failure == "unidentified_before" else
                     ["before", "operation"] if failure == "operation" else
                     ["before", "operation", "after"])
    assert native.requests == (0 if failure in ("unidentified_before", "operation") else 1)


def test_identified_probe_is_read_only_and_save_keeps_original_operation():
    from fort_gym.bench.run.keyboard_save_lua import MENU_SETTLED_IDENTITY_SAVE_LUA
    assert all(operation not in IDENTIFIED_MENU_PROBE_LUA
               for operation in (":logic(", "simulateInput", "hideGuard", "autosave_request = true"))
    assert "table.insert(stack, screen_identity(cur, address))" in IDENTIFIED_MENU_PROBE_LUA
    assert "table.insert(identities, screen_identity(cur, address))" in MENU_DFHACK_IDENTITY_SAVE_LUA
    # Everything after walking the stack, including the single save call and
    # restoration checks, remains byte-identical except for the receipt version.
    start = "local dwarfmode, parent = cur, cur.parent"
    old = MENU_SETTLED_IDENTITY_SAVE_LUA.split(start, 1)[1]
    new = MENU_DFHACK_IDENTITY_SAVE_LUA.split(start, 1)[1]
    assert new.replace("fortgym.native-menu-save/v4", "fortgym.native-menu-save/v3") == old
