-- fort_metrics.lua: plan-agnostic fortress structure detection (read-only).
--
-- Measures what the player actually built, from map state alone — no
-- predefined plan rectangles. Flood-fills open floor outward from every
-- player building to find ENCLOSED spaces (regions fully bounded by walls,
-- buildings, or doors), classifies them functionally by contents, and counts
-- player constructions. Works on any seed/embark.

local json = require('json')

local MAX_COMPONENT_TILES = 400
local MAX_SPACES = 12
local Z_NEIGHBORS = false -- single-z spaces for v1

local attrs = df.tiletype.attrs
local FLOOR_SHAPE = df.tiletype_shape.FLOOR
local WALL_SHAPE = df.tiletype_shape.WALL

-- standable ground that counts as room interior (vegetation and loose rock
-- on a floor do not connect a room to the wild)
local INTERIOR_SHAPES = {
  [df.tiletype_shape.FLOOR] = true,
  [df.tiletype_shape.SHRUB] = true,
  [df.tiletype_shape.SAPLING] = true,
  [df.tiletype_shape.BOULDER] = true,
  [df.tiletype_shape.PEBBLES] = true,
}

local function tile_shape(x, y, z)
  local block = dfhack.maps.getTileBlock(x, y, z)
  if not block then return nil, nil end
  local dx, dy = x % 16, y % 16
  local ok, shape, hidden = pcall(function()
    local attr = attrs[block.tiletype[dx][dy]]
    return attr and attr.shape or nil, block.designation[dx][dy].hidden
  end)
  if not ok then return nil, nil end
  return shape, hidden
end

local function building_at(x, y, z)
  local block = dfhack.maps.getTileBlock(x, y, z)
  if not block then return false end
  local dx, dy = x % 16, y % 16
  local ok, occupied = pcall(function()
    return block.occupancy[dx][dy].building ~= 0
  end)
  return ok and occupied or false
end

-- furniture a dwarf can stand on/next to belongs to the room's interior; a
-- fully furnished bedroom must not stop being a room. Doors, workshops, and
-- anything else seal the boundary.
local INTERIOR_FURNITURE = { bed = true, table = true, chair = true }
local furniture_tiles = {}

local function interior_furniture_at(x, y, z)
  return furniture_tiles[x .. ',' .. y .. ',' .. z] == true
end

-- collect player buildings with their footprints, grouped for classification
local buildings = {}
for _, bld in ipairs(df.global.world.buildings.all) do
  local ok, entry = pcall(function()
    local t = bld:getType()
    local kind = nil
    if t == df.building_type.Bed then kind = 'bed'
    elseif t == df.building_type.Table then kind = 'table'
    elseif t == df.building_type.Chair then kind = 'chair'
    elseif t == df.building_type.Door then kind = 'door'
    elseif t == df.building_type.Workshop then kind = 'workshop'
    end
    if not kind then return nil end
    return {
      kind = kind,
      x1 = bld.x1, y1 = bld.y1, x2 = bld.x2, y2 = bld.y2, z = bld.z,
      cx = bld.centerx, cy = bld.centery,
    }
  end)
  if ok and entry then
    table.insert(buildings, entry)
    if INTERIOR_FURNITURE[entry.kind] then
      for fx = entry.x1, entry.x2 do
        for fy = entry.y1, entry.y2 do
          furniture_tiles[fx .. ',' .. fy .. ',' .. entry.z] = true
        end
      end
    end
  end
end

local constructions = 0
local construction_tiles = {}
pcall(function()
  constructions = #df.global.world.constructions
  -- surface the layout so the agent can see gaps in its own walls; cap the
  -- list and skip the mirrored above-z entries built walls create
  local seen_z = {}
  for _, bld in ipairs(df.global.world.buildings.all) do
    pcall(function() seen_z[bld.z] = true end)
  end
  for _, c in ipairs(df.global.world.constructions) do
    if #construction_tiles >= 80 then break end
    if next(seen_z) == nil or seen_z[c.pos.z] then
      table.insert(construction_tiles, { c.pos.x, c.pos.y, c.pos.z })
    end
  end
end)

-- Queued wall/floor constructions: Construction-type buildings a dwarf has
-- not finished yet (once built they leave buildings.all and become tiletype
-- walls/floors). Rendered on the minimap as 'x' so the agent can tell "wall
-- already queued here" from a real gap. Display only — NEVER counted as a
-- boundary for enclosure detection: an unbuilt wall does not seal a room.
local pending_constructions = 0
local pending_construction_tiles = {}
pcall(function()
  for _, bld in ipairs(df.global.world.buildings.all) do
    local ok_t, is_pending = pcall(function()
      return bld:getType() == df.building_type.Construction
    end)
    if ok_t and is_pending then
      pending_constructions = pending_constructions + 1
      for fx = bld.x1, bld.x2 do
        for fy = bld.y1, bld.y2 do
          pending_construction_tiles[fx .. ',' .. fy .. ',' .. bld.z] = true
        end
      end
    end
  end
end)

-- flood fill open floor from seeds; doors and buildings are boundaries that
-- still close a room; open floor beyond MAX_COMPONENT_TILES means "leaky"
-- (connected to the open map) and therefore not enclosed.
local function flood(seed_x, seed_y, seed_z)
  local visited = {}
  local queue = { { seed_x, seed_y } }
  local tiles = {}
  local enclosed = true
  local function key(x, y) return x .. ',' .. y end
  visited[key(seed_x, seed_y)] = true
  while #queue > 0 do
    local cell = table.remove(queue)
    local x, y = cell[1], cell[2]
    local shape, hidden = tile_shape(x, y, seed_z)
    if shape == nil then
      enclosed = false
    elseif interior_furniture_at(x, y, seed_z) then
      -- beds/tables/chairs are part of the room they furnish
      table.insert(tiles, { x, y })
      if #tiles > MAX_COMPONENT_TILES then
        enclosed = false
        break
      end
      for _, d in ipairs({ { 1, 0 }, { -1, 0 }, { 0, 1 }, { 0, -1 } }) do
        local nx, ny = x + d[1], y + d[2]
        if not visited[key(nx, ny)] then
          visited[key(nx, ny)] = true
          table.insert(queue, { nx, ny })
        end
      end
    elseif building_at(x, y, seed_z) then
      -- other buildings (incl. doors and workshops) close the boundary
    elseif shape == WALL_SHAPE then
      -- walls (and tree trunks) close the boundary
    elseif INTERIOR_SHAPES[shape] and not hidden then
      table.insert(tiles, { x, y })
      if #tiles > MAX_COMPONENT_TILES then
        enclosed = false
        break
      end
      for _, d in ipairs({ { 1, 0 }, { -1, 0 }, { 0, 1 }, { 0, -1 } }) do
        local nx, ny = x + d[1], y + d[2]
        if not visited[key(nx, ny)] then
          visited[key(nx, ny)] = true
          table.insert(queue, { nx, ny })
        end
      end
    else
      -- ramps, stairs, open sky, brooks: leaks to the wild
      enclosed = false
    end
  end
  return tiles, enclosed
end

local function point_in_component(component_lookup, x, y)
  return component_lookup[x .. ',' .. y] == true
end

local spaces = {}
local seen_seed = {}
for _, bld in ipairs(buildings) do
  if #spaces >= MAX_SPACES then break end
  -- seed from tiles adjacent to the building footprint
  for sx = bld.x1 - 1, bld.x2 + 1 do
    for sy = bld.y1 - 1, bld.y2 + 1 do
      local inside_fp = sx >= bld.x1 and sx <= bld.x2 and sy >= bld.y1 and sy <= bld.y2
      local seed_key = sx .. ',' .. sy .. ',' .. bld.z
      if not inside_fp and not seen_seed[seed_key] and #spaces < MAX_SPACES then
        seen_seed[seed_key] = true
        local shape, hidden = tile_shape(sx, sy, bld.z)
        local seedable = interior_furniture_at(sx, sy, bld.z)
          or (INTERIOR_SHAPES[shape] and not hidden and not building_at(sx, sy, bld.z))
        if seedable then
          local tiles, enclosed = flood(sx, sy, bld.z)
          if enclosed and #tiles > 0 then
            local lookup = {}
            for _, t in ipairs(tiles) do
              lookup[t[1] .. ',' .. t[2]] = true
              seen_seed[t[1] .. ',' .. t[2] .. ',' .. bld.z] = true
            end
            local contents = { bed = 0, table = 0, chair = 0, door = 0, workshop = 0 }
            for _, other in ipairs(buildings) do
              if other.z == bld.z then
                -- a building belongs to the space when its footprint touches it
                local touches = false
                for ox = other.x1 - 1, other.x2 + 1 do
                  for oy = other.y1 - 1, other.y2 + 1 do
                    if point_in_component(lookup, ox, oy) then touches = true end
                  end
                end
                if touches then
                  contents[other.kind] = contents[other.kind] + 1
                end
              end
            end
            local function classify()
              if contents.bed > 0 then return 'bedroom' end
              if contents.workshop > 0 then return 'production' end
              if contents.table > 0 and contents.chair > 0 then return 'dining' end
              return 'enclosed_space'
            end
            table.insert(spaces, {
              z = bld.z,
              tiles = #tiles,
              kind = classify(),
              contents = contents,
            })
          end
        end
      end
    end
  end
end

local functional = 0
for _, space in ipairs(spaces) do
  if space.kind ~= 'enclosed_space' then functional = functional + 1 end
end

-- Nearby tree clusters beyond the minimap window. On clearing spawns the
-- fort window can hold zero trunks while forests stand 20 tiles away (G6
-- attempt 1, run 769f5034: the agent chopped blind and wood-starved all
-- run). Bounded read-only scan around the citizens; factual observation
-- content only.
local nearby_trees = { total = 0, clusters = {} }
pcall(function()
  local cx, cy, cz, n = 0, 0, nil, 0
  for _, unit in ipairs(df.global.world.units.active) do
    local ok_c, is_c = pcall(function() return dfhack.units.isCitizen(unit) end)
    if ok_c and is_c and unit.pos then
      cx = cx + unit.pos.x
      cy = cy + unit.pos.y
      cz = unit.pos.z
      n = n + 1
    end
  end
  if n == 0 then return end
  cx, cy = math.floor(cx / n), math.floor(cy / n)
  local RADIUS = 40
  local BUCKET = 16
  local tree_material = df.tiletype_material.TREE
  local buckets = {}
  for x = math.max(0, cx - RADIUS), cx + RADIUS do
    for y = math.max(0, cy - RADIUS), cy + RADIUS do
      local block = dfhack.maps.getTileBlock(x, y, cz)
      if block then
        local dx, dy = x % 16, y % 16
        local ok_t, is_trunk = pcall(function()
          local attr = attrs[block.tiletype[dx][dy]]
          return attr ~= nil and attr.shape == WALL_SHAPE
            and attr.material == tree_material
        end)
        if ok_t and is_trunk then
          nearby_trees.total = nearby_trees.total + 1
          local key = math.floor(x / BUCKET) .. ',' .. math.floor(y / BUCKET)
          local b = buckets[key] or { x = 0, y = 0, count = 0 }
          b.x = b.x + x
          b.y = b.y + y
          b.count = b.count + 1
          buckets[key] = b
        end
      end
    end
  end
  local list = {}
  for _, b in pairs(buckets) do
    table.insert(list, {
      x = math.floor(b.x / b.count),
      y = math.floor(b.y / b.count),
      z = cz,
      count = b.count,
    })
  end
  table.sort(list, function(a, b2) return a.count > b2.count end)
  for i = 1, math.min(3, #list) do
    table.insert(nearby_trees.clusters, list[i])
  end
end)

-- ASCII minimap of the fort area so the agent can see wall geometry and gaps
-- spatially instead of as coordinate lists. Read-only; bounded to 34x34.
local map_origin = nil
local map_rows = {}
do
  local construction_set = {}
  pcall(function()
    for _, c in ipairs(df.global.world.constructions) do
      construction_set[c.pos.x .. ',' .. c.pos.y .. ',' .. c.pos.z] = true
    end
  end)

  local BUILDING_CHARS = {
    bed = 'b', table = 't', chair = 'c', door = 'd', workshop = 'w',
  }
  local building_tile_kind = {}
  local anchor_z_counts = {}
  for _, bld in ipairs(buildings) do
    anchor_z_counts[bld.z] = (anchor_z_counts[bld.z] or 0) + 1
    for fx = bld.x1, bld.x2 do
      for fy = bld.y1, bld.y2 do
        building_tile_kind[fx .. ',' .. fy .. ',' .. bld.z] = bld.kind
      end
    end
  end
  -- citizens anchor the map before any building exists (and are drawn as @)
  local citizen_positions = {}
  pcall(function()
    for _, unit in ipairs(df.global.world.units.active) do
      local ok_c, is_c = pcall(function() return dfhack.units.isCitizen(unit) end)
      if ok_c and is_c and unit.pos then
        table.insert(citizen_positions, { x = unit.pos.x, y = unit.pos.y, z = unit.pos.z })
        anchor_z_counts[unit.pos.z] = (anchor_z_counts[unit.pos.z] or 0) + 0.1
      end
    end
  end)

  local anchor_z, best = nil, 0
  for z, count in pairs(anchor_z_counts) do
    if count > best then anchor_z, best = z, count end
  end

  if anchor_z ~= nil then
    local min_x, min_y = math.huge, math.huge
    local max_x, max_y = -math.huge, -math.huge
    for _, bld in ipairs(buildings) do
      if bld.z == anchor_z then
        min_x = math.min(min_x, bld.x1)
        min_y = math.min(min_y, bld.y1)
        max_x = math.max(max_x, bld.x2)
        max_y = math.max(max_y, bld.y2)
      end
    end
    if min_x == math.huge then
      for _, cpos in ipairs(citizen_positions) do
        if cpos.z == anchor_z then
          min_x = math.min(min_x, cpos.x)
          min_y = math.min(min_y, cpos.y)
          max_x = math.max(max_x, cpos.x)
          max_y = math.max(max_y, cpos.y)
        end
      end
    end
    if min_x == math.huge then
      map_origin = nil
    end
    for key in pairs(construction_set) do
      local cx, cy, cz = key:match('(-?%d+),(-?%d+),(-?%d+)')
      if tonumber(cz) == anchor_z then
        min_x = math.min(min_x, tonumber(cx))
        min_y = math.min(min_y, tonumber(cy))
        max_x = math.max(max_x, tonumber(cx))
        max_y = math.max(max_y, tonumber(cy))
      end
    end
    for key in pairs(pending_construction_tiles) do
      local cx, cy, cz = key:match('(-?%d+),(-?%d+),(-?%d+)')
      if tonumber(cz) == anchor_z then
        min_x = math.min(min_x, tonumber(cx))
        min_y = math.min(min_y, tonumber(cy))
        max_x = math.max(max_x, tonumber(cx))
        max_y = math.max(max_y, tonumber(cy))
      end
    end
    min_x, min_y = min_x - 4, min_y - 4
    max_x, max_y = max_x + 4, max_y + 4
    if max_x - min_x + 1 > 34 then max_x = min_x + 33 end
    if max_y - min_y + 1 > 34 then max_y = min_y + 33 end

    local citizen_lookup = {}
    for _, cpos in ipairs(citizen_positions) do
      if cpos.z == anchor_z then
        citizen_lookup[cpos.x .. ',' .. cpos.y] = true
      end
    end
    map_origin = { min_x, min_y, anchor_z }
    for y = min_y, max_y do
      local row = {}
      for x = min_x, max_x do
        local ch = ' '
        local kind = building_tile_kind[x .. ',' .. y .. ',' .. anchor_z]
        if citizen_lookup[x .. ',' .. y] then
          ch = '@'
          kind = nil
        elseif kind then
          ch = BUILDING_CHARS[kind] or '?'
        elseif pending_construction_tiles[x .. ',' .. y .. ',' .. anchor_z] then
          ch = 'x'
        else
          local shape, hidden = tile_shape(x, y, anchor_z)
          if shape == nil or hidden then
            ch = ' '
          elseif shape == WALL_SHAPE then
            local is_tree = false
            pcall(function()
              local block = dfhack.maps.getTileBlock(x, y, anchor_z)
              local attr = attrs[block.tiletype[x % 16][y % 16]]
              is_tree = attr ~= nil and attr.material == tree_material
            end)
            if construction_set[x .. ',' .. y .. ',' .. anchor_z] then
              ch = 'W'
            elseif is_tree then
              ch = 'T'
            else
              ch = '#'
            end
          elseif shape == FLOOR_SHAPE then
            ch = '.'
          elseif INTERIOR_SHAPES[shape] then
            ch = ','
          else
            ch = '~'
          end
        end
        table.insert(row, ch)
      end
      table.insert(map_rows, table.concat(row))
    end
  end
end

print(json.encode({
  ok = true,
  enclosed_spaces = #spaces,
  functional_rooms = functional,
  spaces = spaces,
  constructions = constructions,
  construction_tiles = construction_tiles,
  pending_constructions = pending_constructions,
  nearby_trees = nearby_trees,
  player_buildings = #buildings,
  map_origin = map_origin,
  map_rows = map_rows,
}))
