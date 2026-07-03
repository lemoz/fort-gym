-- place_furniture.lua: install a finished furniture item as a building.
-- Mirrors the player's b-menu placement: uses an existing produced item and
-- creates a normal install job that a dwarf completes over real time.

local json = require('json')
local buildings = require('dfhack.buildings')
local args = {...}

local kind = tostring(args[1] or '')
local x = tonumber(args[2])
local y = tonumber(args[3])
local z = tonumber(args[4]) or 0

local FURNITURE = {
  Bed = { item_type = df.item_type.BED, building_type = df.building_type.Bed },
  Door = { item_type = df.item_type.DOOR, building_type = df.building_type.Door },
  Table = { item_type = df.item_type.TABLE, building_type = df.building_type.Table },
  Chair = { item_type = df.item_type.CHAIR, building_type = df.building_type.Chair },
}

local spec = FURNITURE[kind]
if not spec then
  print(json.encode({ ok = false, error = 'invalid_kind' }))
  return
end

if not (x and y and z) then
  print(json.encode({ ok = false, error = 'invalid_coordinates' }))
  return
end

local function count_buildings_of_type(building_type)
  local count = 0
  for _, building in ipairs(df.global.world.buildings.all) do
    local ok, matches = pcall(function() return building:getType() == building_type end)
    if ok and matches then count = count + 1 end
  end
  return count
end

local function valid_furniture_item(item)
  if not item or not item.flags then return false end
  if item.flags.garbage_collect
      or item.flags.in_job
      or item.flags.forbid
      or item.flags.hidden
      or item.flags.in_building
      or item.flags.construction
      or item.flags.artifact then
    return false
  end
  if not item.pos or item.pos.x < 0 or item.pos.y < 0 or item.pos.z < 0 then
    return false
  end
  local ok_type, item_type = pcall(function() return item:getType() end)
  return ok_type and item_type == spec.item_type
end

local function find_nearest_furniture_item()
  local best, best_distance = nil, nil
  for _, item in ipairs(df.global.world.items.all) do
    if valid_furniture_item(item) then
      local dx = item.pos.x - x
      local dy = item.pos.y - y
      local dz = item.pos.z - z
      local dist = dx * dx + dy * dy + dz * dz * 100
      if not best_distance or dist < best_distance then
        best, best_distance = item, dist
      end
    end
  end
  return best
end

local item = find_nearest_furniture_item()
if not item then
  print(json.encode({ ok = false, error = 'no_finished_item_available' }))
  return
end

local before_count = count_buildings_of_type(spec.building_type)

local ok, result = pcall(function()
  return buildings.constructBuilding{
    type = spec.building_type,
    x = x,
    y = y,
    z = z,
    items = { item },
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

print(json.encode({
  ok = true,
  kind = kind,
  x = x,
  y = y,
  z = z,
  building_id = result.id,
  jobs_count = result.jobs and #result.jobs or 0,
  item_id = item.id,
  before_count = before_count,
  after_count = count_buildings_of_type(spec.building_type),
}))
