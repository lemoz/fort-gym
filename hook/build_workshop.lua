-- build_workshop.lua: place a bounded safe workshop through DFHack.
-- Plan-agnostic: the placement is only rejected if it is farther than
-- MAX_LOCALITY tiles (Chebyshev) from every existing player building and
-- every citizen. Supports every workshop kind in SUBTYPES below on a
-- conservative dry visible FLOOR-only 3x3 footprint; each new kind here is a
-- bounded action-surface addition, not a shortcut.

local json = require('json')
local buildings = require('dfhack.buildings')
local args = {...}

local kind = tostring(args[1] or '')
local x = tonumber(args[2])
local y = tonumber(args[3])
local z = tonumber(args[4]) or 0

local SUBTYPES = {
  CarpenterWorkshop = df.workshop_type.Carpenters,
  Still = df.workshop_type.Still,
}

local function count_workshops_of_subtype(subtype)
  local count = 0
  local all_buildings = df.global.world.buildings and df.global.world.buildings.all
  if not all_buildings then return 0 end
  for _, building in ipairs(all_buildings) do
    local ok, is_workshop = pcall(function()
      return df.building_workshopst and df.building_workshopst:is_instance(building)
    end)
    if ok and is_workshop and building.type == subtype then
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

local function item_position(item)
  local ok, x, y, z = pcall(function() return dfhack.items.getPosition(item) end)
  if not ok or x == nil or y == nil or z == nil or x < 0 or y < 0 or z < 0 then
    return nil
  end
  return { x = x, y = y, z = z }
end

local function unit_position(unit)
  local ok, x, y, z = pcall(function() return dfhack.units.getPosition(unit) end)
  if not ok or x == nil or y == nil or z == nil or x < 0 or y < 0 or z < 0 then
    return nil
  end
  return { x = x, y = y, z = z }
end

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
      or item.flags.in_inventory
      or item.flags.in_building
      or item.flags.construction
      or item.flags.artifact
      or item.flags.dump
      or item.flags.hostile
      or item.flags.on_fire
      or item.flags.rotten
      or item.flags.trader
      or item.flags.owned
      or item.flags.removed
      or item.flags.encased then
    return false
  end
  local pos = item_position(item)
  if not pos then return false end

  local ok_type, item_type = pcall(function() return item:getType() end)
  if not ok_type or not BUILDING_MATERIAL_ITEM_TYPES[item_type] then
    return false
  end
  local ok_build_mat, is_build_mat = pcall(function() return item:isBuildMat() end)
  if not ok_build_mat or not is_build_mat then return false end

  local block = dfhack.maps.getTileBlock(pos.x, pos.y, pos.z)
  if not block then
    return false
  end
  local designation = block.designation[pos.x % 16][pos.y % 16]
  if not designation or designation.hidden then
    return false
  end
  return true, pos
end

local function distance_sq(pos, x, y, z)
  local dx = pos.x - x
  local dy = pos.y - y
  local dz = pos.z - z
  return dx * dx + dy * dy + dz * dz * 100
end

local function reachable_citizens(x, y, z)
  local reachable = {}
  local target = { x = x, y = y, z = z }
  for _, unit in ipairs(df.global.world.units.active) do
    local ok_citizen, is_citizen = pcall(function()
      return dfhack.units.isCitizen(unit)
        and not dfhack.units.isDead(unit)
        and not (unit.flags1 and unit.flags1.caged)
    end)
    local pos = ok_citizen and is_citizen and unit_position(unit) or nil
    if pos then
      local ok_path, has_path = pcall(function()
        return dfhack.maps.canWalkBetween(pos, target)
      end)
      if ok_path and has_path then table.insert(reachable, { unit = unit, pos = pos }) end
    end
  end
  return reachable
end

local function find_nearest_building_material(x, y, z, citizens)
  local items = df.global.world.items and df.global.world.items.all
  if not items then
    return nil, 0
  end

  local best = nil
  local best_pos = nil
  local best_distance = nil
  local valid_count = 0
  for _, item in ipairs(items) do
    local valid, pos = valid_building_material_item(item)
    if valid and pos then
      valid_count = valid_count + 1
      local reachable = false
      for _, citizen in ipairs(citizens) do
        local ok_path, has_path = pcall(function()
          return dfhack.maps.canWalkBetween(citizen.pos, pos)
        end)
        if ok_path and has_path then
          reachable = true
          break
        end
      end
      if reachable then
        local dist = distance_sq(pos, x, y, z)
        if not best_distance or dist < best_distance then
          best = item
          best_pos = pos
          best_distance = dist
        end
      end
    end
  end
  return best, best_pos, valid_count
end

local subtype = SUBTYPES[kind]
if not subtype then
  print(json.encode({ ok = false, error = 'invalid_kind' }))
  return
end

if not (x and y and z) then
  print(json.encode({ ok = false, error = 'invalid_coordinates' }))
  return
end

if df.global.world.reindex_pathfinding then
  print(json.encode({ ok = false, error = 'path_cache_stale' }))
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

local function footprint_error()
  for tx = x, x + 2 do
    for ty = y, y + 2 do
      local block = dfhack.maps.getTileBlock(tx, ty, z)
      if not block then return 'tile_out_of_bounds' end
      local dx, dy = tx % 16, ty % 16
      local occupied, hidden, open_floor, frozen_liquid, liquid_depth =
        false, true, false, false, 0
      local ok = pcall(function()
        occupied = block.occupancy[dx][dy].building ~= 0
        hidden = block.designation[dx][dy].hidden and true or false
        liquid_depth = tonumber(block.designation[dx][dy].flow_size) or 0
        local attr = df.tiletype.attrs[block.tiletype[dx][dy]]
        open_floor = attr ~= nil and attr.shape == df.tiletype_shape.FLOOR
        frozen_liquid = attr ~= nil
          and attr.material == df.tiletype_material.FROZEN_LIQUID
      end)
      if not ok then return 'tile_state_unreadable' end
      if occupied then return 'tile_occupied_by_building' end
      if hidden then return 'tile_hidden_unexplored' end
      if frozen_liquid then return 'tile_frozen_liquid' end
      if not open_floor then return 'tile_not_open_floor' end
      if liquid_depth > 0 then return 'tile_has_liquid' end
    end
  end
  return nil
end

local placement_error = footprint_error()
if placement_error then
  print(json.encode({ ok = false, error = placement_error }))
  return
end

local citizens = reachable_citizens(x + 1, y + 1, z)
if #citizens == 0 then
  print(json.encode({ ok = false, error = 'workshop_unreachable_from_citizens' }))
  return
end

local before_buildings = df.global.world.buildings and #df.global.world.buildings.all or 0
-- before_carpenter_workshops/after_carpenter_workshops are kept as their own
-- fields (unchanged meaning/values from before this file supported more than
-- one kind) for backward compatibility with existing evidence consumers;
-- before_workshops_of_kind/after_workshops_of_kind are the generalized
-- equivalent that works for any kind in SUBTYPES, including Still.
local before_carpenter_workshops = count_workshops_of_subtype(df.workshop_type.Carpenters)
local before_workshops_of_kind = count_workshops_of_subtype(subtype)
local material_item, material_pos, valid_material_count =
  find_nearest_building_material(x, y, z, citizens)

if not material_item and valid_material_count == 0 then
  print(json.encode({ ok = false, error = 'no_building_material' }))
  return
end
if not material_item then
  print(json.encode({ ok = false, error = 'no_reachable_building_material' }))
  return
end

local ok, result, construct_error = pcall(function()
  return buildings.constructBuilding{
    type = df.building_type.Workshop,
    subtype = subtype,
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
  print(json.encode({ ok = false, error = tostring(construct_error or 'construct_failed') }))
  return
end

local postcondition_ok = false
if result.jobs then
  for _, job in ipairs(result.jobs) do
    if df.job_type[job.job_type] == 'ConstructBuilding' then
      for _, item_ref in ipairs(job.items) do
        if item_ref.item == material_item then
          postcondition_ok = true
          break
        end
      end
    end
    if postcondition_ok then break end
  end
end
if not postcondition_ok then
  local building_id = result.id
  local rollback_call_ok, rollback_error = pcall(function() buildings.deconstruct(result) end)
  local verify_ok, removed = pcall(function() return df.building.find(building_id) == nil end)
  local rollback_ok = rollback_call_ok and verify_ok and removed
  print(json.encode({
    ok = false,
    error = rollback_ok and 'construct_postcondition_failed' or 'rollback_failed',
    building_id = building_id,
    material_item_id = material_item.id,
    rollback_error = rollback_call_ok and nil or tostring(rollback_error),
  }))
  return
end

local after_buildings = df.global.world.buildings and #df.global.world.buildings.all or before_buildings
local after_carpenter_workshops = count_workshops_of_subtype(df.workshop_type.Carpenters)
local after_workshops_of_kind = count_workshops_of_subtype(subtype)

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
  before_workshops_of_kind = before_workshops_of_kind,
  after_workshops_of_kind = after_workshops_of_kind,
  material_item_id = material_item.id,
  material_pos = { material_pos.x, material_pos.y, material_pos.z },
  material_item_type = item_type_name(material_item),
}))
