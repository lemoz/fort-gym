"""Read-only menu identity outside the native save RPC's transient state."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .campaign_save import CampaignSaveError, NativeSaveSnapshotter

MENU_IDENTITY_PROBE_LUA = r"""
local json = require('json')
assert(dfhack.getDFPath() == expected_root, 'Snapshot runtime differs')
assert(dfhack.getDFVersion() == 'v0.47.05 linux64', 'Unsupported native save version')
assert(dfhack.isMapLoaded() and dfhack.world.isFortressMode(), 'Fortress not loaded')
assert(df.global.pause_state and not df.global.ui.main.autosave_request,
       'Identity probe requires a paused fortress with no pending save')
local function selected_id(getter)
    local selected = getter(true)
    return selected and selected.id or -1
end
local top = dfhack.gui.getCurViewscreen(true)
local stack, seen = {}, {}
local cur, child = top, nil
while true do
    assert(cur and #stack < 32, 'Missing or unbounded fortress screen stack')
    local _, addr = cur:sizeof()
    local address = tostring(addr)
    assert(not seen[address] and cur.child == child, 'Invalid native screen chain')
    seen[address] = true
    assert(tostring(cur._type):match('^<type: viewscreen_.*st>$'),
           'Identity probe requires a native screen')
    table.insert(stack, {type = tostring(cur._type), address = address})
    if df.viewscreen_dwarfmodest:is_instance(cur) then break end
    child, cur = cur, cur.parent
end
print(json.encode({
    schema_version = 'fortgym.native-menu-identity/v1',
    native_boundary = {
        dfroot = dfhack.getDFPath(), save_name = df.global.world.cur_savegame.save_dir,
        year = df.global.cur_year, year_tick = df.global.cur_year_tick,
        paused = df.global.pause_state,
        autosave_requested = df.global.ui.main.autosave_request,
    },
    stack = stack,
    ui = {
        focus = dfhack.gui.getFocusString(top),
        unit_id = selected_id(dfhack.gui.getSelectedUnit),
        building_id = selected_id(dfhack.gui.getSelectedBuilding),
        job_id = selected_id(dfhack.gui.getSelectedJob),
        item_id = selected_id(dfhack.gui.getSelectedItem),
        cursor = {x=df.global.cursor.x, y=df.global.cursor.y, z=df.global.cursor.z},
        viewport = {x=df.global.window_x, y=df.global.window_y, z=df.global.window_z},
    },
}))
"""


def validate_menu_stack(stack: Any) -> None:
    if not isinstance(stack, list) or not 1 <= len(stack) <= 32:
        raise CampaignSaveError("Native menu save stack is invalid")
    addresses = set()
    for screen in stack:
        if not isinstance(screen, dict) or (
            not isinstance(screen.get("type"), str)
            or re.fullmatch(r"<type: viewscreen_\w+st>", screen["type"]) is None
            or not isinstance(screen.get("address"), str)
            or not screen["address"]
            or screen["address"] in addresses
        ):
            raise CampaignSaveError("Native menu save stack identity is invalid")
        addresses.add(screen["address"])
    if stack[-1]["type"] != "<type: viewscreen_dwarfmodest>":
        raise CampaignSaveError("Native menu save lacks a fortress ancestor")


def validate_ui_identity(ui: Any) -> None:
    if not isinstance(ui, dict) or (
        set(ui) != {"focus", "unit_id", "building_id", "job_id", "item_id", "cursor", "viewport"}
        or not isinstance(ui["focus"], str) or not ui["focus"]
        or any(type(ui[field]) is not int or ui[field] < -1
               for field in ("unit_id", "building_id", "job_id", "item_id"))
        or any(not isinstance(ui[field], dict) or set(ui[field]) != {"x", "y", "z"}
               or any(type(value) is not int for value in ui[field].values())
               for field in ("cursor", "viewport"))
    ):
        raise CampaignSaveError("Native menu identity is invalid")


def validate_identity_probe(value: Any, dfroot: Path) -> dict:
    """Reject unknown/unpaused observations before attempting a native save."""
    if not isinstance(value, dict) or (
        set(value) != {"schema_version", "native_boundary", "stack", "ui"}
        or value["schema_version"] != "fortgym.native-menu-identity/v1"
        or not isinstance(value["native_boundary"], dict)
    ):
        raise CampaignSaveError("Native menu identity probe is invalid")
    boundary = value["native_boundary"]
    if boundary.get("dfroot") != str(dfroot.resolve()) or (
        boundary.get("autosave_requested") is not False
    ):
        raise CampaignSaveError("Native menu identity probe runtime or completion differs")
    NativeSaveSnapshotter._boundary({**boundary, "ok": True})
    validate_menu_stack(value["stack"])
    validate_ui_identity(value["ui"])
    return value


def validate_settled_identity(receipt: dict, dfroot: Path) -> None:
    before = validate_identity_probe(receipt.get("identity_before"), dfroot)
    after = validate_identity_probe(receipt.get("identity_after"), dfroot)
    if any(probe["native_boundary"] != receipt["native_before"]
           or probe["stack"] != receipt["original_stack"] for probe in (before, after)):
        raise CampaignSaveError("Native menu identity probe boundary or stack changed")
    if before["ui"] != after["ui"] or before["ui"] != receipt["ui_before"]:
        raise CampaignSaveError("Native menu identity changed across save RPC")
