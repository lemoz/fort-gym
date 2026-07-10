-- place_furniture.lua: install a finished furniture item as a building.
-- Conservative b-menu subset: installs on dry visible FLOOR targets, uses an
-- existing produced item, and creates a normal job completed over real time.
-- Plan-agnostic: the tile is only rejected if it is farther than MAX_LOCALITY
-- tiles (Chebyshev) from every existing player building and every citizen.

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

local function count_buildings_of_type(building_type)
  local count = 0
  for _, building in ipairs(df.global.world.buildings.all) do
    local ok, matches = pcall(function() return building:getType() == building_type end)
    if ok and matches then count = count + 1 end
  end
  return count
end

local function item_position(item)
  local ok, ix, iy, iz = pcall(function() return dfhack.items.getPosition(item) end)
  if not ok or ix == nil or iy == nil or iz == nil or ix < 0 or iy < 0 or iz < 0 then
    return nil
  end
  return { x = ix, y = iy, z = iz }
end

local function unit_position(unit)
  local ok, ux, uy, uz = pcall(function() return dfhack.units.getPosition(unit) end)
  if not ok or ux == nil or uy == nil or uz == nil or ux < 0 or uy < 0 or uz < 0 then
    return nil
  end
  return { x = ux, y = uy, z = uz }
end

local function valid_furniture_item(item)
  if not item or not item.flags then return false end
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
  local block = dfhack.maps.getTileBlock(pos.x, pos.y, pos.z)
  if not block then return false end
  local designation = block.designation[pos.x % 16][pos.y % 16]
  if not designation or designation.hidden then return false end
  local ok_type, item_type = pcall(function() return item:getType() end)
  return ok_type and item_type == spec.item_type, pos
end

local function reachable_citizens()
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

local function find_nearest_furniture_item(citizens)
  local best, best_pos, best_distance = nil, nil, nil
  local valid_count = 0
  for _, item in ipairs(df.global.world.items.all) do
    local valid, pos = valid_furniture_item(item)
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
        local dx = pos.x - x
        local dy = pos.y - y
        local dz = pos.z - z
        local dist = dx * dx + dy * dy + dz * dz * 100
        if not best_distance or dist < best_distance then
          best, best_pos, best_distance = item, pos, dist
        end
      end
    end
  end
  return best, best_pos, valid_count
end

-- Classify the target tile BEFORE attempting placement so a failure carries
-- the reason a player would see on screen instead of a bare construct_failed.
local function tile_placement_error()
  local block = dfhack.maps.getTileBlock(x, y, z)
  if not block then return 'tile_out_of_bounds' end
  local dx, dy = x % 16, y % 16
  local occupied, is_floor, hidden, liquid_depth = false, false, false, 0
  local ok = pcall(function()
    occupied = block.occupancy[dx][dy].building ~= 0
    local attr = df.tiletype.attrs[block.tiletype[dx][dy]]
    is_floor = attr ~= nil and attr.shape == df.tiletype_shape.FLOOR
    hidden = block.designation[dx][dy].hidden
    liquid_depth = tonumber(block.designation[dx][dy].flow_size) or 0
  end)
  if not ok then return 'tile_state_unreadable' end
  if occupied then return 'tile_occupied_by_building' end
  if hidden then return 'tile_hidden_unexplored' end
  if not is_floor then return 'tile_not_open_floor' end
  if liquid_depth > 0 then return 'tile_has_liquid' end
  return nil
end

local tile_error = tile_placement_error()
if tile_error then
  print(json.encode({ ok = false, error = tile_error }))
  return
end

local citizens = reachable_citizens()
if #citizens == 0 then
  print(json.encode({ ok = false, error = 'tile_unreachable_from_citizens' }))
  return
end

local item, item_pos, valid_item_count = find_nearest_furniture_item(citizens)
if not item and valid_item_count == 0 then
  print(json.encode({ ok = false, error = 'no_finished_item_available' }))
  return
end
if not item then
  print(json.encode({ ok = false, error = 'no_reachable_finished_item' }))
  return
end

local before_count = count_buildings_of_type(spec.building_type)

local ok, result, construct_error = pcall(function()
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
  print(json.encode({ ok = false, error = tostring(construct_error or 'construct_failed') }))
  return
end

local postcondition_ok = false
if result.jobs then
  for _, job in ipairs(result.jobs) do
    if df.job_type[job.job_type] == 'ConstructBuilding' then
      for _, item_ref in ipairs(job.items) do
        if item_ref.item == item then
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
    item_id = item.id,
    rollback_error = rollback_call_ok and nil or tostring(rollback_error),
  }))
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
  item_pos = { item_pos.x, item_pos.y, item_pos.z },
  before_count = before_count,
  after_count = count_buildings_of_type(spec.building_type),
}))
