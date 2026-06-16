-- build_workshop.lua: place a bounded safe workshop through DFHack.

local json = require('json')
local buildings = require('dfhack.buildings')
local args = {...}

local kind = tostring(args[1] or '')
local x = tonumber(args[2])
local y = tonumber(args[3])
local z = tonumber(args[4]) or 0

local function count_carpenter_workshops()
  local count = 0
  local all_buildings = df.global.world.buildings and df.global.world.buildings.all
  if not all_buildings then return 0 end
  for _, building in ipairs(all_buildings) do
    local ok, is_workshop = pcall(function()
      return df.building_workshopst and df.building_workshopst:is_instance(building)
    end)
    if ok and is_workshop and building.type == df.workshop_type.Carpenters then
      count = count + 1
    end
  end
  return count
end

if kind ~= 'CarpenterWorkshop' then
  print(json.encode({ ok = false, error = 'invalid_kind' }))
  return
end

if not (x and y and z) then
  print(json.encode({ ok = false, error = 'invalid_coordinates' }))
  return
end

local before_buildings = df.global.world.buildings and #df.global.world.buildings.all or 0
local before_carpenter_workshops = count_carpenter_workshops()

local ok, result = pcall(function()
  return buildings.constructBuilding{
    type = df.building_type.Workshop,
    subtype = df.workshop_type.Carpenters,
    x = x,
    y = y,
    z = z,
    width = 3,
    height = 3,
    full_rectangle = true,
  }
end)

if not ok then
  print(json.encode({ ok = false, error = tostring(result) }))
  return
end

if not result then
  print(json.encode({ ok = false, error = 'construct_failed' }))
  return
end

local after_buildings = df.global.world.buildings and #df.global.world.buildings.all or before_buildings
local after_carpenter_workshops = count_carpenter_workshops()

print(json.encode({
  ok = true,
  kind = kind,
  x = x,
  y = y,
  z = z,
  width = 3,
  height = 3,
  building_id = result.id,
  construction_stage = result.construction_stage,
  jobs_count = result.jobs and #result.jobs or 0,
  before_buildings = before_buildings,
  after_buildings = after_buildings,
  before_carpenter_workshops = before_carpenter_workshops,
  after_carpenter_workshops = after_carpenter_workshops,
}))
