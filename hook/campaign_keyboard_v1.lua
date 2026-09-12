-- Native interface events, not direct job/build insertion. One event per call
-- permits ordinary UI frames between events while the world remains paused.
-- https://docs.dfhack.org/en/0.47.05-r8/docs/dev/Lua%20API.html
local json = require('json')
local gui = require('gui')
local args = {...}
local result = {
  schema_version='fortgym.campaign-keyboard-native/v1', ok=false,
  command_mutation='not_attempted', keys_sent=0,
}
local function integer(n)
  return type(n)=='number' and n==n and n~=math.huge and n~=-math.huge
    and n==math.floor(n)
end
local function snapshot()
  local view = dfhack.gui.getCurViewscreen(true)
  return {
    dfroot=dfhack.getDFPath(), year=df.global.cur_year,
    year_tick=df.global.cur_year_tick, paused=df.global.pause_state,
    save_name=df.global.world.cur_savegame.save_dir,
    viewscreen_type=view and tostring(view._type) or 'none',
    focus=view and dfhack.gui.getFocusString(view) or 'none',
  }
end
local mode, expected_root, year, tick = args[1], args[2], tonumber(args[3]), tonumber(args[4])
local expected_save = args[5]
if (mode~='probe' and mode~='key' and mode~='catalog') or type(expected_root)~='string'
    or expected_root=='' or not integer(year) or year<0
    or not integer(tick) or tick<0 or tick>=403200
    or type(expected_save)~='string' or #args>(mode=='catalog' and 2053 or 105)
    or (mode=='key' and (#args~=6 or expected_save=='')) then
  result.error='invalid_keyboard_request'
  print(json.encode(result))
  return
end

local lock_ok, lock_error = pcall(dfhack.with_suspend, function()
  if not dfhack.isMapLoaded() or not dfhack.world.isFortressMode() then
    result.error='fortress_not_loaded'
    return
  end
  result.before = snapshot()
  if result.before.dfroot~=expected_root or result.before.year~=year
      or result.before.year_tick~=tick or result.before.paused~=true
      or (mode=='key' and result.before.save_name~=expected_save) then
    result.error='keyboard_boundary_mismatch'
    return
  end
  result.mode=mode
  if mode=='catalog' then
    -- Bulk read-only compatibility audit. Never dispatch any candidate event.
    -- Keep both lists so failures identify every mismatch in a single run.
    result.supported={}
    result.unsupported={}
    for index=6,#args do
      local key=args[index]
      local supported=type(key)=='string' and df.interface_key[key]~=nil
        and key~='NONE' and key~='KEYBINDING_COMPLETE'
      table.insert(supported and result.supported or result.unsupported, key)
    end
    result.checked=#args-5
    result.after=snapshot()
    result.ok=#result.unsupported==0
    if not result.ok then result.error='native_catalog_mismatch' end
    return
  end
  for index=6,#args do
    if type(args[index])~='string' or df.interface_key[args[index]]==nil then
      result.error='unsupported_native_key'
      result.invalid_key_index=index-5
      return
    end
  end
  if mode=='probe' then
    result.ok=true
    result.after=snapshot()
    return
  end
  local view = dfhack.gui.getCurViewscreen(true)
  if not view then result.error='native_viewscreen_unavailable'; return end
  result.key=args[6]
  -- A thrown native input call may already have changed the UI or game orders.
  -- Never assert non-execution or replay it merely because the call failed.
  result.command_mutation='unknown'
  result.keys_sent=nil
  local input_ok, input_error = pcall(gui.simulateInput, view, df.interface_key[args[6]])
  result.paused_after_input=df.global.pause_state
  -- Simulation is independently requested through advance_ticks. Restore pause
  -- inside this same core lock, even if D_PAUSE was pressed or input threw.
  df.global.pause_state=true
  result.after=snapshot()
  if not input_ok then
    result.error='native_input_error: '..tostring(input_error)
    return
  end
  result.keys_sent=1
  if result.after.dfroot~=expected_root or result.after.year~=year
      or result.after.year_tick~=tick or result.after.save_name~=result.before.save_name
      or result.after.paused~=true then
    result.error='keyboard_changed_native_boundary'
    return
  end
  result.command_mutation='completed'
  result.ok=true
end)
if not lock_ok then result.ok=false; result.error=tostring(lock_error) end
print(json.encode(result))
