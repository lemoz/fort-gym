-- set_labor.lua: flip one labor on one citizen, mirroring the player's
-- v-p-l (view-unit preferences-labors) toggle. Setting
-- u.status.labors[df.unit_labor.X] = <bool> is exactly the mechanic the game
-- uses to decide which citizen may take a matching queued job; it completes no
-- work itself — a dwarf must still path to and perform the job over real time.
-- Never mutates tiles, designations, buildings, or any other unit field.

local json = require('json')
local args = {...}

-- Friendly labor name -> df.unit_labor enum name. Whitelist mirrors the module
-- constant in dfhack_backend.py; the hook independently guards each enum with a
-- pcall (df.unit_labor.X ~= nil) so a missing enum on this DF build is reported
-- honestly as unsupported_labor rather than crashing the transport.
local LABOR_WHITELIST = {
  mine = 'MINE',
  woodcutting = 'CUTWOOD',
  carpentry = 'CARPENTER',
  masonry = 'MASON',
  farming = 'PLANT',
  herbalism = 'HERBALIST',
  brewing = 'BREWER',
  fishing = 'FISH',
  construction = 'BUILD_BUILDING',
  cooking = 'COOK',
}

local function to_int(v)
  local n = tonumber(v)
  if not n then return nil end
  return math.floor(n)
end

local function sanitize(text)
  -- CP437 safety: raw DF name/text broke a probe transport today, so strip any
  -- byte that is not word/space/punctuation before it reaches json.encode.
  local ok, cleaned = pcall(function()
    return tostring(text):gsub('[^%w %p]', '?')
  end)
  if ok then return cleaned end
  return '?'
end

local unit_id = to_int(args[1])
local labor_name = args[2]
local enable_raw = args[3]

if unit_id == nil or labor_name == nil then
  print(json.encode({ ok = false, error = 'bad_args' }))
  return
end

-- enable: '1'/'true' -> true, anything else -> false
local enable = (enable_raw == '1' or enable_raw == 'true' or enable_raw == true)

local enum_name = LABOR_WHITELIST[labor_name]
if enum_name == nil then
  print(json.encode({
    ok = false,
    error = 'unsupported_labor',
    labor = sanitize(labor_name),
  }))
  return
end

-- Guard the enum on THIS DF build: report unsupported_labor if the enum name
-- is absent on 0.47.05 rather than indexing nil and crashing.
local ok_enum, labor_enum = pcall(function() return df.unit_labor[enum_name] end)
if not ok_enum or labor_enum == nil then
  print(json.encode({
    ok = false,
    error = 'unsupported_labor',
    labor = sanitize(labor_name),
    enum = sanitize(enum_name),
  }))
  return
end

-- Find the active unit by id.
local target = nil
local ok_walk = pcall(function()
  for _, unit in ipairs(df.global.world.units.active) do
    if unit and unit.id == unit_id then
      target = unit
      return
    end
  end
end)

if not ok_walk then
  print(json.encode({ ok = false, error = 'unit_list_unavailable' }))
  return
end

if target == nil then
  print(json.encode({
    ok = false,
    error = 'unit_not_found',
    reason = 'unit_not_found',
    unit_id = unit_id,
  }))
  return
end

local ok_citizen, is_citizen = pcall(function()
  return dfhack.units.isCitizen(target) and true or false
end)
if not ok_citizen or not is_citizen then
  print(json.encode({
    ok = false,
    error = 'not_a_citizen',
    reason = 'not_a_citizen',
    unit_id = unit_id,
  }))
  return
end

-- Read before state, flip, read after. A no-op (already at requested state) is
-- honestly visible as before == after with changed=false.
local ok_before, before = pcall(function()
  return target.status.labors[labor_enum] and true or false
end)
if not ok_before then
  print(json.encode({ ok = false, error = 'labor_read_failed', unit_id = unit_id }))
  return
end

local ok_write = pcall(function()
  target.status.labors[labor_enum] = enable
end)
if not ok_write then
  print(json.encode({ ok = false, error = 'labor_write_failed', unit_id = unit_id }))
  return
end

local ok_after, after = pcall(function()
  return target.status.labors[labor_enum] and true or false
end)
if not ok_after then
  print(json.encode({ ok = false, error = 'labor_read_failed', unit_id = unit_id }))
  return
end

-- Neutral profession field for evidence context (name optional, sanitized).
local profession = ''
pcall(function()
  profession = df.profession[target.profession] or tostring(target.profession)
end)

print(json.encode({
  ok = true,
  unit_id = unit_id,
  labor = sanitize(labor_name),
  enum = sanitize(enum_name),
  requested = enable,
  labor_before = before,
  labor_after = after,
  labor_changed = (before ~= after),
  profession = sanitize(profession),
}))
