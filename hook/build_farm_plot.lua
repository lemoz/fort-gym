-- build_farm_plot.lua: place a bounded farm plot through DFHack.
-- Mirrors the player's b-p menu: buildings.constructBuilding with
-- building_type.FarmPlot across a rectangular footprint (max 5x5). Unlike
-- workshops/furniture/constructions, a farm plot consumes no material item.
-- Plan-agnostic: the placement is only rejected for locality if farther than
-- MAX_LOCALITY tiles (Chebyshev) from every existing player building and
-- every citizen (same 24-anchor pattern as build_workshop.lua/
-- build_construction.lua/place_furniture.lua). Obvious per-tile placement
-- problems (occupied by a building, hidden/unexplored, not open floor) are
-- classified before attempting construction, reusing the same tile check as
-- place_furniture.lua's tile_placement_error. DF's real soil/mud farmability
-- requirement is NOT determined here (that needs live-save verification) --
-- if the engine itself refuses the placement for that reason, it is reported
-- honestly as construct_failed rather than guessed at.

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

if not near_fort(rx1, ry1) then
  print(json.encode({ ok = false, error = 'too_far_from_fort' }))
  return
end

-- Classify every tile in the footprint before attempting placement -- same
-- checks as place_furniture.lua's tile_placement_error. This does NOT
-- verify DF's real soil/mud farmability requirement, only the obvious cases.
local function tile_placement_error(x, y)
  local block = dfhack.maps.getTileBlock(x, y, z)
  if not block then return 'tile_out_of_bounds' end
  local dx, dy = x % 16, y % 16
  local occupied, is_floor, hidden = false, false, false
  pcall(function()
    occupied = block.occupancy[dx][dy].building ~= 0
    local attr = df.tiletype.attrs[block.tiletype[dx][dy]]
    is_floor = attr ~= nil and attr.shape == df.tiletype_shape.FLOOR
    hidden = block.designation[dx][dy].hidden
  end)
  if occupied then return 'tile_occupied_by_building' end
  if hidden then return 'tile_hidden_unexplored' end
  if not is_floor then return 'tile_not_open_floor' end
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
}))
