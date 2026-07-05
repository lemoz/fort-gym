-- build_workshop.lua: place a bounded safe workshop through DFHack.
-- Plan-agnostic: the placement is only rejected if it is farther than
-- MAX_LOCALITY tiles (Chebyshev) from every existing player building and
-- every citizen.

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

local BUILDING_MATERIAL_ITEM_TYPES = {
  [df.item_type.BAR] = true,
  [df.item_type.BLOCKS] = true,
  [df.item_type.BOULDER] = true,
  [df.item_type.WOOD] = true,
}

local function item_type_name(item)
  local ok, item_type = pcall(function() return item:getType() end)
  if not ok then return '' end
  return tostring(item_type)
end

local function valid_building_material_item(item)
  if not item or not item.flags then
    return false
  end
  if item.flags.garbage_collect
      or item.flags.in_job
      or item.flags.forbid
      or item.flags.hidden
      or item.flags.construction
      or item.flags.artifact then
    return false
  end
  if not item.pos or item.pos.x < 0 or item.pos.y < 0 or item.pos.z < 0 then
    return false
  end

  local ok_type, item_type = pcall(function() return item:getType() end)
  if not ok_type or not BUILDING_MATERIAL_ITEM_TYPES[item_type] then
    return false
  end

  local block = dfhack.maps.getTileBlock(item.pos.x, item.pos.y, item.pos.z)
  if not block then
    return false
  end
  local designation = block.designation[item.pos.x % 16][item.pos.y % 16]
  if not designation or designation.hidden then
    return false
  end
  return true
end

local function distance_sq(item, x, y, z)
  local dx = item.pos.x - x
  local dy = item.pos.y - y
  local dz = item.pos.z - z
  return dx * dx + dy * dy + dz * dz * 100
end

local function find_nearest_building_material(x, y, z)
  local items = df.global.world.items and df.global.world.items.all
  if not items then
    return nil
  end

  local best = nil
  local best_distance = nil
  for _, item in ipairs(items) do
    if valid_building_material_item(item) then
      local dist = distance_sq(item, x, y, z)
      if not best_distance or dist < best_distance then
        best = item
        best_distance = dist
      end
    end
  end
  return best
end

if kind ~= 'CarpenterWorkshop' then
  print(json.encode({ ok = false, error = 'invalid_kind' }))
  return
end

if not (x and y and z) then
  print(json.encode({ ok = false, error = 'invalid_coordinates' }))
  return
end

local MAX_LOCALITY = 24

local function collect_locality_anchors()
  local anchors = {}
  local ok_buildings = pcall(function()
    for _, bld in ipairs(df.global.world.buildings.all) do
      table.insert(anchors, { x = bld.centerx, y = bld.centery })
    end
  end)
  if not ok_buildings then
    anchors = {}
  end
  local ok_units = pcall(function()
    for _, unit in ipairs(df.global.world.units.active) do
      local ok_citizen, is_citizen = pcall(function()
        return dfhack.units.isCitizen(unit)
      end)
      if ok_citizen and is_citizen and unit.pos then
        table.insert(anchors, { x = unit.pos.x, y = unit.pos.y })
      end
    end
  end)
  if not ok_units then
    -- keep whatever building anchors were already collected
  end
  return anchors
end

local function near_fort(tx, ty)
  local anchors = collect_locality_anchors()
  if #anchors == 0 then return false end
  for _, anchor in ipairs(anchors) do
    local dx = math.abs(anchor.x - tx)
    local dy = math.abs(anchor.y - ty)
    if math.max(dx, dy) <= MAX_LOCALITY then
      return true
    end
  end
  return false
end

if not near_fort(x, y) then
  print(json.encode({ ok = false, error = 'too_far_from_fort' }))
  return
end

local before_buildings = df.global.world.buildings and #df.global.world.buildings.all or 0
local before_carpenter_workshops = count_carpenter_workshops()
local material_item = find_nearest_building_material(x, y, z)

if not material_item then
  print(json.encode({ ok = false, error = 'no_building_material' }))
  return
end

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
    items = { material_item },
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
  material_item_id = material_item.id,
  material_item_type = item_type_name(material_item),
}))
