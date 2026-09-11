-- Experimental one-key binding-set dispatch, not a gameplay strategy.
-- Keys are resolved without menu context from the pinned interface.txt file.
local json = require('json')
local gui = require('gui')
local args = {...}
local result = {schema_version='fortgym.experimental-binding-set/v1', ok=false,
  input_calls=0, command_mutation='not_attempted'}
local function integer(n)
  return type(n)=='number' and n==math.floor(n) and n~=math.huge and n~=-math.huge
end
local root, year, tick, save = args[1], tonumber(args[2]), tonumber(args[3]), args[4]
if type(root)~='string' or root=='' or not integer(year) or year<0
    or not integer(tick) or tick<0 or tick>=403200 or type(save)~='string'
    or save=='' or #args<5 or #args>516 then
  result.error='invalid_request'
  print(json.encode(result))
  return
end
local function snapshot()
  local view = dfhack.gui.getCurViewscreen(true)
  return {dfroot=dfhack.getDFPath(), year=df.global.cur_year,
    year_tick=df.global.cur_year_tick, paused=df.global.pause_state,
    save_name=df.global.world.cur_savegame.save_dir,
    focus=view and dfhack.gui.getFocusString(view) or 'none'}
end
local function same_boundary(point)
  return point.dfroot==root and point.year==year and point.year_tick==tick
    and point.save_name==save and point.paused==true
end
local locked, lock_error = pcall(dfhack.with_suspend, function()
  if not dfhack.isMapLoaded() or not dfhack.world.isFortressMode() then
    result.error='fortress_not_loaded'
    return
  end
  result.before = snapshot()
  if not same_boundary(result.before) then
    result.error='boundary_mismatch'
    return
  end
  local keys, names, seen = {}, {}, {}
  for index=5,#args do
    local name = args[index]
    local code = type(name)=='string' and df.interface_key[name] or nil
    if not integer(code) or seen[code] or name=='NONE' or name=='KEYBINDING_COMPLETE' then
      result.error='invalid_native_event'
      return
    end
    seen[code]=true
    table.insert(keys, code)
    table.insert(names, name)
  end
  local view = dfhack.gui.getCurViewscreen(true)
  if not view then result.error='no_viewscreen'; return end
  result.events=names
  result.input_calls=1
  result.command_mutation='attempted'
  -- One call containing the entire set, never a sequence of alias presses.
  local accepted, input_error = pcall(gui.simulateInput, view, keys)
  result.paused_after_input=df.global.pause_state
  df.global.pause_state=true
  result.after=snapshot()
  if not accepted then result.error='native_input_error: '..tostring(input_error); return end
  if not same_boundary(result.after) then result.error='boundary_changed'; return end
  result.command_mutation='completed'
  result.ok=true
end)
if not locked then result.error=tostring(lock_error) end
print(json.encode(result))
