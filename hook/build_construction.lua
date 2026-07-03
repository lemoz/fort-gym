-- build_construction.lua: place bounded wall/floor constructions.
-- Mirrors the player's b-C menu: each tile gets a construction building with
-- a material item attached; dwarves with the right labor build them over
-- real time. Never creates items; max 10 tiles per call. Plan-agnostic: tiles
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

local function valid_material(item)
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
  return ok_type and MATERIAL_ITEM_TYPES[item_type] or false
end

local function find_material(x, y, z)
  local best, best_distance = nil, nil
  for _, item in ipairs(df.global.world.items.all) do
    if valid_material(item) then
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
for tx = rx1, rx2 do
  for ty = ry1, ry2 do
    local tile_block = dfhack.maps.getTileBlock(tx, ty, z1)
    local occupied_by_building = false
    local already_wall = false
    if tile_block then
      local bdx, bdy = tx % 16, ty % 16
      pcall(function()
        occupied_by_building = tile_block.occupancy[bdx][bdy].building ~= 0
        local attr = df.tiletype.attrs[tile_block.tiletype[bdx][bdy]]
        already_wall = attr ~= nil and attr.shape == df.tiletype_shape.WALL
      end)
    end
    if not near_fort(tx, ty) then
      table.insert(failed, { x = tx, y = ty, error = 'too_far_from_fort' })
    elseif occupied_by_building then
      table.insert(failed, { x = tx, y = ty, error = 'tile_occupied_by_building' })
    elseif already_wall then
      table.insert(failed, { x = tx, y = ty, error = 'already_wall' })
    else
      local material = find_material(tx, ty, z1)
      if not material then
        table.insert(failed, { x = tx, y = ty, error = 'no_building_material' })
      else
        local ok, result = pcall(function()
          return buildings.constructBuilding{
            type = df.building_type.Construction,
            subtype = subtype,
            x = tx,
            y = ty,
            z = z1,
            items = { material },
          }
        end)
        if ok and result then
          table.insert(placed, { x = tx, y = ty, building_id = result.id })
        else
          table.insert(failed, {
            x = tx,
            y = ty,
            error = ok and 'construct_failed' or tostring(result),
          })
        end
      end
    end
  end
end

print(json.encode({
  ok = #placed > 0,
  kind = kind,
  rect = { rx1, ry1, z1, rx2, ry2, z1 },
  placed_count = #placed,
  failed_count = #failed,
  placed = placed,
  failed = failed,
  error = #placed == 0 and 'no_tiles_placed' or nil,
}))
