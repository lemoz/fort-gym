-- build_construction.lua: place bounded wall/floor constructions.
-- Conservative b-C subset: dry visible FLOOR targets only. Each tile gets a
-- construction building with a material item attached; dwarves with the right
-- labor build them over real time. Never creates items; max 10 tiles per call. Plan-agnostic: tiles
-- are only rejected if they are farther than MAX_LOCALITY tiles (Chebyshev)
-- from every existing player building and every citizen.

local json = require('json')
local buildings = require('dfhack.buildings')
local args = {...}

local kind = tostring(args[1] or '')

local function to_int(v)
  local n = tonumber(v)
  if not n then return nil end
  return math.floor(n)
end

local x1 = to_int(args[2])
local y1 = to_int(args[3])
local z1 = to_int(args[4])
local x2 = to_int(args[5]) or x1
local y2 = to_int(args[6]) or y1

local SUBTYPES = {
  Wall = df.construction_type.Wall,
  Floor = df.construction_type.Floor,
}

local subtype = SUBTYPES[kind]
if not subtype then
  print(json.encode({ ok = false, error = 'invalid_kind' }))
  return
end

if not (x1 and y1 and z1) then
  print(json.encode({ ok = false, error = 'invalid_coordinates' }))
  return
end

if df.global.world.reindex_pathfinding then
  print(json.encode({ ok = false, error = 'path_cache_stale' }))
  return
end

local rx1, ry1 = math.min(x1, x2), math.min(y1, y2)
local rx2, ry2 = math.max(x1, x2), math.max(y1, y2)
local total_tiles = (rx2 - rx1 + 1) * (ry2 - ry1 + 1)
if total_tiles > 10 then
  print(json.encode({ ok = false, error = 'too_many_tiles' }))
  return
end

local MATERIAL_ITEM_TYPES = {
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

local function valid_material(item)
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
  local ok_type, item_type = pcall(function() return item:getType() end)
  if not ok_type or not MATERIAL_ITEM_TYPES[item_type] then return false end
  local ok_build_mat, is_build_mat = pcall(function() return item:isBuildMat() end)
  if not ok_build_mat or not is_build_mat then return false end
  local block = dfhack.maps.getTileBlock(pos.x, pos.y, pos.z)
  if not block then return false end
  local designation = block.designation[pos.x % 16][pos.y % 16]
  return designation ~= nil and not designation.hidden, pos
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

local function find_material(x, y, z, citizens)
  local best, best_pos, best_distance = nil, nil, nil
  local valid_count = 0
  for _, item in ipairs(df.global.world.items.all) do
    local valid, pos = valid_material(item)
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

local locality_anchors = collect_locality_anchors()

local completed_construction_tiles = {}
pcall(function()
  for _, construction in ipairs(df.global.world.constructions) do
    local pos = construction.pos
    completed_construction_tiles[pos.x .. ',' .. pos.y .. ',' .. pos.z] = true
  end
end)

local function near_fort(x, y)
  if #locality_anchors == 0 then return false end
  for _, anchor in ipairs(locality_anchors) do
    local dx = math.abs(anchor.x - x)
    local dy = math.abs(anchor.y - y)
    if math.max(dx, dy) <= MAX_LOCALITY then
      return true
    end
  end
  return false
end

local placed = {}
local failed = {}
local rollback_failed = false

local function rollback_building(building)
  local building_id = building and building.id or -1
  local call_ok, call_error = pcall(function() buildings.deconstruct(building) end)
  local verify_ok, removed = pcall(function() return df.building.find(building_id) == nil end)
  return call_ok and verify_ok and removed, call_ok and nil or tostring(call_error)
end

for tx = rx1, rx2 do
  for ty = ry1, ry2 do
    local tile_block = dfhack.maps.getTileBlock(tx, ty, z1)
    local occupied_by_building = false
    local already_wall = false
    local already_construction = completed_construction_tiles[tx .. ',' .. ty .. ',' .. z1] or false
    local hidden = true
    local open_floor = false
    local frozen_liquid = false
    local liquid_depth = 0
    local tile_shape = nil
    local tiletype_name = nil
    if tile_block then
      local bdx, bdy = tx % 16, ty % 16
      pcall(function()
        occupied_by_building = tile_block.occupancy[bdx][bdy].building ~= 0
        local tiletype = tile_block.tiletype[bdx][bdy]
        local attr = df.tiletype.attrs[tiletype]
        already_wall = attr ~= nil and attr.shape == df.tiletype_shape.WALL
        open_floor = attr ~= nil and attr.shape == df.tiletype_shape.FLOOR
        frozen_liquid = attr ~= nil
          and attr.material == df.tiletype_material.FROZEN_LIQUID
        hidden = tile_block.designation[bdx][bdy].hidden and true or false
        liquid_depth = tonumber(tile_block.designation[bdx][bdy].flow_size) or 0
        pcall(function()
          tiletype_name = tostring(df.tiletype[tiletype] or tiletype)
          tile_shape = attr ~= nil and tostring(df.tiletype_shape[attr.shape] or attr.shape) or nil
        end)
      end)
    end
    if not near_fort(tx, ty) then
      table.insert(failed, { x = tx, y = ty, z = z1, error = 'too_far_from_fort' })
    elseif not tile_block then
      table.insert(failed, { x = tx, y = ty, z = z1, error = 'tile_out_of_bounds' })
    elseif occupied_by_building then
      table.insert(failed, { x = tx, y = ty, z = z1, error = 'tile_occupied_by_building' })
    elseif already_wall then
      table.insert(failed, { x = tx, y = ty, z = z1, error = 'already_wall' })
    elseif already_construction then
      table.insert(failed, { x = tx, y = ty, z = z1, error = 'already_construction' })
    elseif hidden then
      table.insert(failed, { x = tx, y = ty, z = z1, error = 'tile_hidden_unexplored' })
    elseif frozen_liquid then
      table.insert(failed, { x = tx, y = ty, z = z1, error = 'tile_frozen_liquid' })
    elseif not open_floor then
      table.insert(failed, {
        x = tx,
        y = ty,
        z = z1,
        error = 'tile_not_open_floor',
        tile_shape = tile_shape,
        tiletype = tiletype_name,
      })
    elseif liquid_depth > 0 then
      table.insert(failed, { x = tx, y = ty, z = z1, error = 'tile_has_liquid' })
    else
      local citizens = reachable_citizens(tx, ty, z1)
      local material, material_pos, valid_material_count = find_material(tx, ty, z1, citizens)
      if #citizens == 0 then
        table.insert(failed, { x = tx, y = ty, z = z1, error = 'tile_unreachable_from_citizens' })
      elseif not material and valid_material_count == 0 then
        table.insert(failed, { x = tx, y = ty, z = z1, error = 'no_building_material' })
      elseif not material then
        table.insert(failed, { x = tx, y = ty, z = z1, error = 'no_reachable_building_material' })
      else
        local ok, result, construct_error = pcall(function()
          return buildings.constructBuilding{
            type = df.building_type.Construction,
            subtype = subtype,
            x = tx,
            y = ty,
            z = z1,
            items = { material },
          }
        end)
        local postcondition_ok = false
        if ok and result and result.jobs then
          for _, job in ipairs(result.jobs) do
            if df.job_type[job.job_type] == 'ConstructBuilding' then
              for _, item_ref in ipairs(job.items) do
                if item_ref.item == material then
                  postcondition_ok = true
                  break
                end
              end
            end
            if postcondition_ok then break end
          end
        end
        if postcondition_ok then
          table.insert(placed, {
            x = tx,
            y = ty,
            z = z1,
            building_id = result.id,
            material_item_id = material.id,
            material_pos = { material_pos.x, material_pos.y, material_pos.z },
          })
        else
          local building_id = result and result.id or nil
          local rollback_ok, rollback_error = true, nil
          if ok and result then
            rollback_ok, rollback_error = rollback_building(result)
          end
          local failure_error = nil
          if not ok then
            failure_error = tostring(result)
          elseif not result then
            failure_error = tostring(construct_error or 'construct_failed')
          elseif not rollback_ok then
            failure_error = 'rollback_failed'
          else
            failure_error = 'construct_postcondition_failed'
          end
          table.insert(failed, {
            x = tx,
            y = ty,
            z = z1,
            error = failure_error,
            building_id = building_id,
            material_item_id = material.id,
            rollback_error = rollback_error,
          })
          if not rollback_ok then rollback_failed = true end
        end
      end
    end
    if rollback_failed then break end
  end
  if rollback_failed then break end
end

print(json.encode({
  ok = #placed > 0 and #failed == 0 and not rollback_failed,
  partial = #placed > 0 and #failed > 0,
  kind = kind,
  rect = { rx1, ry1, z1, rx2, ry2, z1 },
  placed_count = #placed,
  failed_count = #failed,
  placed = placed,
  failed = failed,
  error = rollback_failed and 'rollback_failed'
      or (#placed > 0 and #failed > 0 and 'partial_placement'
          or (#placed == 0 and 'no_tiles_placed' or nil)),
}))
