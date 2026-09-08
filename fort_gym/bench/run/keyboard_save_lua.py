"""Paused save operation for DFHack 0.47.05-r8; no gameplay input.

hideGuard retains each actual viewscreen and restores it after the callback.
The exposed dwarf-mode logic method processes the autosave flag while paused.
See the version-matched DFHack Lua API and quicksave.lua. This is operational
snapshot maintenance, not a model-accessible action or world-editing helper.
"""

MENU_SAVE_LUA = r"""
local json = require('json')
assert(dfhack.getDFPath() == expected_root, 'Snapshot runtime differs')
assert(dfhack.getDFVersion() == 'v0.47.05 linux64', 'Unsupported native save version')
assert(dfhack.isMapLoaded() and dfhack.world.isFortressMode(), 'Fortress not loaded')
assert(df.global.pause_state and not df.global.ui.main.autosave_request,
       'Snapshot requires paused fortress with no pending save')
local function boundary()
    return {
        dfroot = dfhack.getDFPath(), save_name = df.global.world.cur_savegame.save_dir,
        year = df.global.cur_year, year_tick = df.global.cur_year_tick,
        paused = df.global.pause_state,
        autosave_requested = df.global.ui.main.autosave_request,
    }
end
local before = boundary()
local top = dfhack.gui.getCurViewscreen(true)
local screens, identities, seen = {}, {}, {}
local cur, child = top, nil
while true do
    assert(cur and #screens < 32, 'Missing or unbounded fortress screen stack')
    local _, addr = cur:sizeof()
    local address = tostring(addr)
    assert(not seen[address] and cur.child == child, 'Invalid native screen chain')
    seen[address] = true
    assert(tostring(cur._type):match('^<type: viewscreen_.*st>$'),
           'Snapshot cannot hide a non-native screen')
    table.insert(identities, {type = tostring(cur._type), address = address})
    if df.viewscreen_dwarfmodest:is_instance(cur) then break end
    table.insert(screens, cur)
    child, cur = cur, cur.parent
end
local dwarfmode, parent = cur, cur.parent
local old_backup = df.global.d_init.flags4.AUTOBACKUP
local logic_calls = 0
local function perform(index)
    if index <= #screens then
        return dfhack.screen.hideGuard(screens[index], perform, index + 1)
    end
    assert(dfhack.gui.getCurViewscreen(true) == dwarfmode)
    assert(df.global.pause_state and df.global.cur_year == before.year
           and df.global.cur_year_tick == before.year_tick)
    df.global.d_init.flags4.AUTOBACKUP = false
    df.global.ui.main.autosave_request = true
    logic_calls = logic_calls + 1
    dwarfmode:logic()
end
local ok, err = xpcall(function() perform(1) end, debug.traceback)
df.global.d_init.flags4.AUTOBACKUP = old_backup
local restored = dfhack.gui.getCurViewscreen(true) == top and top.child == nil
cur = dfhack.gui.getCurViewscreen(true)
child = nil
for _, original in ipairs(screens) do
    restored = restored and cur == original and cur.child == child
    child, cur = cur, cur and cur.parent
end
restored = restored and cur == dwarfmode and cur.child == child and cur.parent == parent
local receipt = {
    schema_version = 'fortgym.native-menu-save/v1', ok = ok,
    native_before = before, native_after = boundary(),
    menu_stack_restored = restored, original_stack = identities,
    backup_setting_restored = df.global.d_init.flags4.AUTOBACKUP == old_backup,
    gameplay_keys_sent = 0, native_logic_calls_requested = logic_calls,
    dfhack_version = dfhack.getDFHackVersion(),
}
if not ok then receipt.error = tostring(err) end
print(json.encode(receipt))
"""

# Keep the executed v1 operation intact. V2 adds semantic UI identity evidence;
# raster animation is not a menu-state invariant in paused Dwarf Fortress.
MENU_IDENTITY_SAVE_LUA = MENU_SAVE_LUA.replace(
    "local before = boundary()",
    r"""
local function selected_id(getter)
    local selected = getter(true)
    return selected and selected.id or -1
end
local function ui_identity()
    return {
        focus = dfhack.gui.getFocusString(dfhack.gui.getCurViewscreen(true)),
        unit_id = selected_id(dfhack.gui.getSelectedUnit),
        building_id = selected_id(dfhack.gui.getSelectedBuilding),
        job_id = selected_id(dfhack.gui.getSelectedJob),
        item_id = selected_id(dfhack.gui.getSelectedItem),
        cursor = {x=df.global.cursor.x, y=df.global.cursor.y, z=df.global.cursor.z},
        viewport = {x=df.global.window_x, y=df.global.window_y, z=df.global.window_z},
    }
end
local ui_before = ui_identity()
local before = boundary()
""",
).replace(
    "schema_version = 'fortgym.native-menu-save/v1', ok = ok,",
    "schema_version = 'fortgym.native-menu-save/v2', ok = ok,\n"
    "    ui_before = ui_before, ui_after = ui_identity(),",
)

# V3 keeps the inline helper readings as diagnostics and binds verification to
# separate read-only RPCs before and after saving. The native operation is equal.
MENU_SETTLED_IDENTITY_SAVE_LUA = MENU_IDENTITY_SAVE_LUA.replace(
    "fortgym.native-menu-save/v2", "fortgym.native-menu-save/v3"
)
