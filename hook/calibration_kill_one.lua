-- calibration_kill_one.lua: schedule exactly one real citizen death for the
-- provider-free death-cause calibration scenario.
--
-- This hook is intentionally narrower than DFHack's version-dependent
-- `exterminate` command. It selects the lowest-id living, active citizen with
-- blood, sets that unit's blood to zero, and lets the next real game tick
-- create the ordinary death and incident records consumed by g7_evidence.lua.
-- It does not write any measurement or death-cause evidence itself.

local json = require('json')

local function result(payload)
  print(json.encode(payload))
end

if not dfhack.isMapLoaded() then
  result({
    ok = false,
    fixture = 'dfhack_bounded_friendly_bloodloss',
    target = 'citizen',
    limit = 1,
    method = 'blood_loss_next_tick',
    error = 'map_not_loaded',
  })
  return
end

local target = nil
local ok_walk, walk_error = pcall(function()
  for _, unit in ipairs(df.global.world.units.active) do
    local eligible = unit
      and unit.body
      and unit.body.blood_max > 0
      and unit.body.blood_count > 0
      and not unit.flags1.inactive
      and not unit.flags1.caged
      and not unit.flags1.chained
      and dfhack.units.isCitizen(unit, true)
      and not dfhack.units.isDead(unit)
    if eligible and (target == nil or unit.id < target.id) then
      target = unit
    end
  end
end)

if not ok_walk then
  result({
    ok = false,
    fixture = 'dfhack_bounded_friendly_bloodloss',
    target = 'citizen',
    limit = 1,
    method = 'blood_loss_next_tick',
    error = 'unit_scan_failed:' .. tostring(walk_error),
  })
  return
end

if target == nil then
  result({
    ok = false,
    fixture = 'dfhack_bounded_friendly_bloodloss',
    target = 'citizen',
    limit = 1,
    method = 'blood_loss_next_tick',
    error = 'no_eligible_citizen',
  })
  return
end

local blood_before = tonumber(target.body.blood_count) or -1
local ok_mutate, mutate_error = pcall(function()
  target.body.blood_count = 0
  if target.animal then
    target.animal.vanish_countdown = 2
  end
end)

if not ok_mutate or target.body.blood_count ~= 0 then
  result({
    ok = false,
    fixture = 'dfhack_bounded_friendly_bloodloss',
    target = 'citizen',
    limit = 1,
    method = 'blood_loss_next_tick',
    unit_id = target.id,
    blood_before = blood_before,
    blood_after = tonumber(target.body.blood_count) or -1,
    error = 'fixture_mutation_failed:' .. tostring(mutate_error),
  })
  return
end

local race_token = '?'
pcall(function()
  race_token = tostring(
    df.global.world.raws.creatures.all[target.race].creature_id
  )
end)

result({
  ok = true,
  fixture = 'dfhack_bounded_friendly_bloodloss',
  target = 'citizen',
  limit = 1,
  method = 'blood_loss_next_tick',
  unit_id = target.id,
  race_token = race_token,
  blood_before = blood_before,
  blood_after = tonumber(target.body.blood_count) or -1,
})
