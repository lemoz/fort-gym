-- build_farm_plot.lua: place a bounded farm plot through DFHack.
-- Mirrors the player's b-p menu: buildings.constructBuilding with
-- building_type.FarmPlot across a rectangular footprint (max 5x5). Unlike
-- workshops/furniture/constructions, a farm plot consumes no material item.
-- Plan-agnostic: the placement is only rejected for locality if farther than
-- MAX_LOCALITY tiles (Chebyshev) from every existing player building and
-- every citizen (same 24-anchor pattern as build_workshop.lua/
-- build_construction.lua/place_furniture.lua). Obvious per-tile placement
-- problems are classified before attempting construction. This helper accepts
-- only the native soil/grass material set used by DFHack 0.47.05 quickfort's
-- farm-plot placement check. Muddy stone is intentionally unsupported until it
-- has its own native proof; unknown cases fail closed instead of creating an
-- impossible plot through constructBuilding.

local json = require('json')
local buildings = require('dfhack.buildings')
local args = {...}

local function to_int(v)
  local n = tonumber(v)
  if not n then return nil end
  return math.floor(n)
end

local x1 = to_int(args[1])
local y1 = to_int(args[2])
local z = to_int(args[3])
local x2 = to_int(args[4]) or x1
local y2 = to_int(args[5]) or y1

if not (x1 and y1 and z) then
  print(json.encode({ ok = false, error = 'invalid_coordinates' }))
  return
end

local rx1, ry1 = math.min(x1, x2), math.min(y1, y2)
local rx2, ry2 = math.max(x1, x2), math.max(y1, y2)
local width = rx2 - rx1 + 1
local height = ry2 - ry1 + 1

if width > 5 or height > 5 then
  print(json.encode({ ok = false, error = 'rect_too_large' }))
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

-- Check all four corners of the footprint, not just one -- for a rect up to
-- 5x5, a single-corner check can pass while the opposite corner sits past
-- the 24-tile locality bound (build_construction.lua, the actual structural
-- sibling for a bounded rect placement, checks near_fort per-tile for
-- exactly this reason).
local corners = {
  { rx1, ry1 },
  { rx1, ry2 },
  { rx2, ry1 },
  { rx2, ry2 },
}
for _, corner in ipairs(corners) do
  if not near_fort(corner[1], corner[2]) then
    print(json.encode({ ok = false, error = 'too_far_from_fort' }))
    return
  end
end

local FARMABLE_MATERIALS = {
  [df.tiletype_material.SOIL] = true,
  [df.tiletype_material.GRASS_LIGHT] = true,
  [df.tiletype_material.GRASS_DARK] = true,
  [df.tiletype_material.GRASS_DRY] = true,
  [df.tiletype_material.GRASS_DEAD] = true,
  [df.tiletype_material.PLANT] = true,
}

local function scan_building_at_tile(x, y)
  return pcall(function()
    local all = df.global.world.buildings and df.global.world.buildings.all
    if not all then error('building_list_unavailable') end
    for _, building in ipairs(all) do
      if building.z == z
          and x >= building.x1 and x <= building.x2
          and y >= building.y1 and y <= building.y2 then
        return building
      end
    end
    return nil
  end)
end

-- Classify every tile before attempting placement. The order matters: hidden
-- state is checked before tiletype material. Scan buildings.all independently
-- of the stale occupancy bit used by findAtTile in DFHack 0.47.05.
local function tile_placement_error(x, y)
  local block = dfhack.maps.getTileBlock(x, y, z)
  if not block then return 'tile_out_of_bounds' end
  local dx, dy = x % 16, y % 16
  local designation = block.designation[dx][dy]
  if not designation then return 'tile_designation_unreadable' end
  if designation.hidden then return 'tile_hidden_unexplored' end
  if designation.flow_size > 0 then return 'tile_has_liquid' end

  local ok_building, building = scan_building_at_tile(x, y)
  if not ok_building then return 'tile_building_state_unreadable' end
  if building or block.occupancy[dx][dy].building ~= 0 then
    return 'tile_occupied_by_building'
  end

  local ok_attr, attr = pcall(function()
    return df.tiletype.attrs[block.tiletype[dx][dy]]
  end)
  if not ok_attr or not attr then return 'tiletype_unreadable' end
  if attr.material == df.tiletype_material.FROZEN_LIQUID then
    return 'tile_frozen_liquid'
  end
  if attr.shape ~= df.tiletype_shape.FLOOR then return 'tile_not_open_floor' end
  if not FARMABLE_MATERIALS[attr.material] then
    return 'tile_not_native_farmable_soil'
  end
  return nil
end

local failed_tiles = {}
for tx = rx1, rx2 do
  for ty = ry1, ry2 do
    local reason = tile_placement_error(tx, ty)
    if reason then
      table.insert(failed_tiles, { x = tx, y = ty, error = reason })
    end
  end
end

if #failed_tiles > 0 then
  print(json.encode({
    ok = false,
    error = 'tile_not_placeable',
    -- key name "failed" matches build_construction.lua's per-tile failure
    -- list so the observation encoder's existing "Failed tiles:" rendering
    -- picks it up without new plumbing.
    failed = failed_tiles,
  }))
  return
end

local function count_farm_plots()
  local count = 0
  local all_buildings = df.global.world.buildings and df.global.world.buildings.all
  if not all_buildings then return 0 end
  for _, building in ipairs(all_buildings) do
    local ok, matches = pcall(function()
      return building:getType() == df.building_type.FarmPlot
    end)
    if ok and matches then count = count + 1 end
  end
  return count
end

local before_buildings = df.global.world.buildings and #df.global.world.buildings.all or 0
local before_farm_plots = count_farm_plots()

-- Farm plots take no material item, unlike workshops/furniture/constructions
-- (open engine-mechanics question: verify live that constructBuilding never
-- requires one for FarmPlot; if it does, this reports construct_failed
-- honestly rather than guessing at a material to pass).
local ok, result = pcall(function()
  return buildings.constructBuilding{
    type = df.building_type.FarmPlot,
    x = rx1,
    y = ry1,
    z = z,
    width = width,
    height = height,
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
local after_farm_plots = count_farm_plots()

print(json.encode({
  ok = true,
  kind = 'FarmPlot',
  x = rx1,
  y = ry1,
  z = z,
  width = width,
  height = height,
  building_id = result.id,
  construction_stage = result.construction_stage,
  jobs_count = result.jobs and #result.jobs or 0,
  before_buildings = before_buildings,
  after_buildings = after_buildings,
  before_farm_plots = before_farm_plots,
  after_farm_plots = after_farm_plots,
  farmability = 'native_soil_material',
  native_farmable_tiles = width * height,
}))
