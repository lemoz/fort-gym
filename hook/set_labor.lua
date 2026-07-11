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
  construction = 'BUILD_CONSTRUCTION',
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

local function sanitized_profession(unit)
  local ok, profession = pcall(function()
    local value = df.profession[unit.profession]
    if value == nil then value = tostring(unit.profession) end
    return sanitize(value)
  end)
  if ok then return profession end
  return sanitize('?')
end

local unit_id = to_int(args[1])
local labor_name = args[2]
local enable_raw = args[3]
local profession = sanitize('?')

if unit_id == nil or labor_name == nil then
  print(json.encode({ ok = false, error = 'bad_args', profession = profession }))
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
    profession = profession,
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
    profession = profession,
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
  print(json.encode({
    ok = false,
    error = 'unit_list_unavailable',
    profession = profession,
  }))
  return
end

if target == nil then
  print(json.encode({
    ok = false,
    error = 'unit_not_found',
    reason = 'unit_not_found',
    unit_id = unit_id,
    profession = profession,
  }))
  return
end

profession = sanitized_profession(target)

local ok_citizen, is_citizen = pcall(function()
  return dfhack.units.isCitizen(target) and true or false
end)
if not ok_citizen or not is_citizen then
  print(json.encode({
    ok = false,
    error = 'not_a_citizen',
    reason = 'not_a_citizen',
    unit_id = unit_id,
    profession = profession,
  }))
  return
end

-- Children and babies are citizens for population purposes, but the player's
-- labor toggle only applies to adults. Unknown eligibility fails closed before
-- any labor field is read or written.
local ok_adult, is_adult = pcall(function()
  return dfhack.units.isAdult(target)
end)
if not ok_adult or type(is_adult) ~= 'boolean' then
  print(json.encode({
    ok = false,
    error = 'labor_eligibility_unavailable',
    reason = 'labor_eligibility_unavailable',
    unit_id = unit_id,
    profession = profession,
  }))
  return
end

if not is_adult then
  print(json.encode({
    ok = false,
    error = 'unit_not_labor_eligible',
    reason = 'unit_not_labor_eligible',
    unit_id = unit_id,
    profession = profession,
  }))
  return
end

-- Read before state, flip, and attest the requested state. Any failed write or
-- readback is rolled back to the observed before state. An unverified rollback
-- is explicit so the governed runner terminates instead of treating a possible
-- mutation as an ordinary rejection.
local ok_before, before = pcall(function()
  return target.status.labors[labor_enum] and true or false
end)
if not ok_before then
  print(json.encode({
    ok = false,
    error = 'labor_read_failed',
    unit_id = unit_id,
    profession = profession,
  }))
  return
end

local ok_write = pcall(function()
  target.status.labors[labor_enum] = enable
end)

local ok_after, after = pcall(function()
  return target.status.labors[labor_enum] and true or false
end)

if not ok_write or not ok_after or after ~= enable then
  local rollback_write_ok = pcall(function()
    target.status.labors[labor_enum] = before
  end)
  local rollback_read_ok, rollback_after = pcall(function()
    return target.status.labors[labor_enum] and true or false
  end)
  local rollback_verified = rollback_write_ok
    and rollback_read_ok
    and rollback_after == before
  local commit_error = 'labor_write_failed'
  if ok_write and not ok_after then
    commit_error = 'labor_readback_failed'
  elseif ok_write and after ~= enable then
    commit_error = 'labor_readback_mismatch'
  end
  print(json.encode({
    ok = false,
    error = commit_error,
    reason = commit_error,
    unit_id = unit_id,
    labor = sanitize(labor_name),
    enum = sanitize(enum_name),
    requested = enable,
    labor_before = before,
    labor_after = ok_after and after or false,
    labor_after_known = ok_after,
    rollback_after = rollback_read_ok and rollback_after or false,
    rollback_after_known = rollback_read_ok,
    rollback_verified = rollback_verified,
    mutation_state = rollback_verified and 'rolled_back' or 'unknown',
    profession = profession,
  }))
  return
end

print(json.encode({
  ok = true,
  unit_id = unit_id,
  labor = sanitize(labor_name),
  enum = sanitize(enum_name),
  requested = enable,
  labor_before = before,
  labor_after = after,
  labor_after_known = true,
  labor_changed = (before ~= after),
  profession = sanitize(profession),
}))
