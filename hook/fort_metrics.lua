-- fort_metrics.lua: plan-agnostic fortress structure detection (read-only).
--
-- Measures what the player actually built, from map state alone — no
-- predefined plan rectangles. Flood-fills open floor outward from every
-- player building to find ENCLOSED spaces (regions fully bounded by walls,
-- buildings, or doors), classifies them functionally by contents, and counts
-- player constructions. Works on any seed/embark.

local json = require('json')
local args = {...}

local function to_int(value)
  local number = tonumber(value)
  if not number then return nil end
  return math.floor(number)
end

-- Optional focus is supplied only from the model's own accepted channel
-- action. Without all six bounded coordinates this hook remains fully
-- plan-agnostic and emits no access target.
local access_focus_rect = nil
if #args >= 6 then
  local x1 = to_int(args[1])
  local y1 = to_int(args[2])
  local z1 = to_int(args[3])
  local x2 = to_int(args[4])
  local y2 = to_int(args[5])
  local z2 = to_int(args[6])
  if x1 and y1 and z1 and x2 and y2 and z2 and z1 == z2 then
    local rx1, ry1 = math.min(x1, x2), math.min(y1, y2)
    local rx2, ry2 = math.max(x1, x2), math.max(y1, y2)
    if rx2 - rx1 + 1 <= 30 and ry2 - ry1 + 1 <= 30 then
      access_focus_rect = { rx1, ry1, z1, rx2, ry2, z1 }
    end
  end
end

local MAX_COMPONENT_TILES = 400
local MAX_SPACES = 12
local MAX_ROOM_OPEN_TILE_SAMPLES = 16
local MIN_ROOM_INTERIOR_TILES = 2
local Z_NEIGHBORS = false -- single-z spaces for v1

local attrs = df.tiletype.attrs
local FLOOR_SHAPE = df.tiletype_shape.FLOOR
local WALL_SHAPE = df.tiletype_shape.WALL
local STAIR_UP_SHAPE = df.tiletype_shape.STAIR_UP
local STAIR_DOWN_SHAPE = df.tiletype_shape.STAIR_DOWN
local STAIR_UPDOWN_SHAPE = df.tiletype_shape.STAIR_UPDOWN
local RAMP_SHAPE = df.tiletype_shape.RAMP
local RAMP_TOP_SHAPE = df.tiletype_shape.RAMP_TOP
local EMPTY_SHAPE = df.tiletype_shape.EMPTY
local FROZEN_LIQUID_MATERIAL = df.tiletype_material.FROZEN_LIQUID
local TREE_MATERIAL = df.tiletype_material.TREE

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
  if not block then return nil, nil, nil end
  local dx, dy = x % 16, y % 16
  local ok_hidden, hidden = pcall(function()
    return block.designation[dx][dy].hidden
  end)
  if not ok_hidden then return nil, nil, nil end
  -- Hidden tiles are opaque. Do not read tiletype attributes and do not let a
  -- hidden wall close a room flood, since either would leak unexplored geology.
  if hidden then return nil, true, nil end
  local ok, shape, material = pcall(function()
    local attr = attrs[block.tiletype[dx][dy]]
    return attr and attr.shape or nil, attr and attr.material or nil
  end)
  if not ok then return nil, nil, nil end
  return shape, false, material
end

local function stable_interior_shape(shape, material)
  return INTERIOR_SHAPES[shape] and material ~= FROZEN_LIQUID_MATERIAL
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

local completed_building_tiles = {}

local function completed_building_at(x, y, z)
  return completed_building_tiles[x .. ',' .. y .. ',' .. z] == true
end

local function building_is_complete(bld)
  local ok, stage, max_stage = pcall(function()
    return bld:getBuildStage(), bld:getMaxBuildStage()
  end)
  stage = ok and tonumber(stage) or nil
  max_stage = ok and tonumber(max_stage) or nil
  local read_ok = ok and stage ~= nil and max_stage ~= nil and max_stage > 0
  return read_ok and stage >= max_stage, read_ok
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
local building_scan_complete = true
for _, bld in ipairs(df.global.world.buildings.all) do
  local is_complete, stage_read_ok = building_is_complete(bld)
  if not stage_read_ok then building_scan_complete = false end
  if is_complete then
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
      -- Only measured room fixtures seal a flood-fill boundary. Walkable or
      -- unclassified buildings such as farm plots must not become fake walls.
      for fx = bld.x1, bld.x2 do
        for fy = bld.y1, bld.y2 do
          completed_building_tiles[fx .. ',' .. fy .. ',' .. bld.z] = true
        end
      end
      return {
        id = bld.id,
        kind = kind,
        x1 = bld.x1, y1 = bld.y1, x2 = bld.x2, y2 = bld.y2, z = bld.z,
        cx = bld.centerx, cy = bld.centery,
      }
    end)
    if not ok then building_scan_complete = false
    elseif entry then
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
end

local raw_construction_records = 0
local constructions = 0
local construction_tiles = {}
local construction_details = {}
local completed_construction_tiles = {}
local construction_tiles_complete = true
local construction_scan_ok = pcall(function()
  raw_construction_records = #df.global.world.constructions
  -- Verify each record against the current native tile shape. This removes
  -- mirrored/stale records without a lossy z-level heuristic and preserves the
  -- construction kind needed for exact owned-claim matching.
  for _, c in ipairs(df.global.world.constructions) do
    local shape = tile_shape(c.pos.x, c.pos.y, c.pos.z)
    local kind = nil
    if shape == WALL_SHAPE then kind = 'Wall'
    elseif shape == FLOOR_SHAPE then kind = 'Floor'
    elseif shape == nil then construction_tiles_complete = false
    end
    if kind then
      local key = c.pos.x .. ',' .. c.pos.y .. ',' .. c.pos.z
      if not completed_construction_tiles[key] then
        completed_construction_tiles[key] = true
        table.insert(construction_tiles, { c.pos.x, c.pos.y, c.pos.z })
        table.insert(construction_details, {
          x = c.pos.x, y = c.pos.y, z = c.pos.z, kind = kind,
        })
      end
    end
  end
  constructions = #construction_tiles
end)
construction_tiles_complete = construction_scan_ok and construction_tiles_complete

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

-- Flood-fill open floor from seeds. Doors and buildings close boundaries.
-- Oversized components are sensor-incomplete, not evidence of an open room.
local component_scan_truncated = false
local function flood(seed_x, seed_y, seed_z)
  local visited = {}
  local queue = { { seed_x, seed_y } }
  local tiles = {}
  local enclosed = true
  local truncated = false
  local function key(x, y) return x .. ',' .. y end
  visited[key(seed_x, seed_y)] = true
  while #queue > 0 do
    local cell = table.remove(queue)
    local x, y = cell[1], cell[2]
    local shape, hidden, material = tile_shape(x, y, seed_z)
    if shape == nil then
      enclosed = false
    elseif material == FROZEN_LIQUID_MATERIAL then
      -- Seasonal ice is not stable room interior; thawing opens the region.
      enclosed = false
    elseif interior_furniture_at(x, y, seed_z) then
      -- beds/tables/chairs are part of the room they furnish
      table.insert(tiles, { x, y })
      if #tiles > MAX_COMPONENT_TILES then
        component_scan_truncated = true
        truncated = true
        break
      end
      for _, d in ipairs({ { 1, 0 }, { -1, 0 }, { 0, 1 }, { 0, -1 } }) do
        local nx, ny = x + d[1], y + d[2]
        if not visited[key(nx, ny)] then
          visited[key(nx, ny)] = true
          table.insert(queue, { nx, ny })
        end
      end
    elseif completed_building_at(x, y, seed_z) then
      -- completed buildings (incl. doors and workshops) close the boundary
    elseif shape == WALL_SHAPE then
      -- walls (and tree trunks) close the boundary
    elseif stable_interior_shape(shape, material) and not hidden then
      table.insert(tiles, { x, y })
      if #tiles > MAX_COMPONENT_TILES then
        component_scan_truncated = true
        truncated = true
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
  return tiles, enclosed, truncated
end

local function point_in_component(component_lookup, x, y)
  return component_lookup[x .. ',' .. y] == true
end

local function room_accessibility(open_tiles, open_tile_count)
  -- Accessibility is a final-state native path query, not an inference from a
  -- door count. A room with no unoccupied interior tile is not usable.
  if #open_tiles == 0 then return false, true, 'no_open_interior_tile' end
  local citizen_seen = false
  local citizen_classification_failed = false
  local query_seen = false
  local query_failed = false
  for _, unit in ipairs(df.global.world.units.active) do
    local ok_citizen, is_citizen = pcall(function()
      return dfhack.units.isCitizen(unit)
        and not dfhack.units.isDead(unit)
        and not (unit.flags1 and unit.flags1.caged)
    end)
    if not ok_citizen then citizen_classification_failed = true end
    if ok_citizen and is_citizen and unit.pos then
      citizen_seen = true
      for _, tile in ipairs(open_tiles) do
        local target = { x = tile[1], y = tile[2], z = tile[3] }
        local ok_path, connected = pcall(function()
          return dfhack.maps.canWalkBetween(
            { x = unit.pos.x, y = unit.pos.y, z = unit.pos.z },
            target
          )
        end)
        if ok_path then
          query_seen = true
          if connected then return true, true, 'citizen_path_confirmed' end
        else
          query_failed = true
        end
      end
    end
  end
  if not citizen_seen then return false, false, 'no_live_citizen_for_path_query' end
  if query_failed or not query_seen then return false, false, 'path_query_incomplete' end
  if citizen_classification_failed then
    return false, false, 'citizen_classification_incomplete'
  end
  if open_tile_count > #open_tiles then
    return false, false, 'open_tile_samples_truncated'
  end
  return false, true, 'no_citizen_path'
end

local spaces = {}
local seen_seed = {}
local spaces_truncated = false
for _, bld in ipairs(buildings) do
  -- seed from tiles adjacent to the building footprint
  for sx = bld.x1 - 1, bld.x2 + 1 do
    for sy = bld.y1 - 1, bld.y2 + 1 do
      local inside_fp = sx >= bld.x1 and sx <= bld.x2 and sy >= bld.y1 and sy <= bld.y2
      local seed_key = sx .. ',' .. sy .. ',' .. bld.z
      if not inside_fp and not seen_seed[seed_key] and not spaces_truncated then
        seen_seed[seed_key] = true
        local shape, hidden, material = tile_shape(sx, sy, bld.z)
        local seedable = interior_furniture_at(sx, sy, bld.z)
          or (stable_interior_shape(shape, material)
            and not hidden
            and not completed_building_at(sx, sy, bld.z))
        if seedable then
          local tiles, enclosed, component_truncated = flood(sx, sy, bld.z)
          if enclosed and not component_truncated and #tiles > 0 then
            local lookup = {}
            for _, t in ipairs(tiles) do
              lookup[t[1] .. ',' .. t[2]] = true
              seen_seed[t[1] .. ',' .. t[2] .. ',' .. bld.z] = true
            end
            local contents = { bed = 0, table = 0, chair = 0, door = 0, workshop = 0 }
            local touching_building_ids = {}
            local touching_building_kinds = {}
            local boundary_building_ids = {}
            local boundary_door_ids = {}
            for _, other in ipairs(buildings) do
              if other.z == bld.z then
                -- Interior furniture overlaps the component. Boundary
                -- buildings must occupy an exact four-neighbor boundary tile;
                -- diagonal proximity is not room membership or door closure.
                local touches = false
                local boundary_touches = false
                for ox = other.x1, other.x2 do
                  for oy = other.y1, other.y2 do
                    if point_in_component(lookup, ox, oy) then
                      touches = true
                    else
                      for _, d in ipairs({ { 1, 0 }, { -1, 0 }, { 0, 1 }, { 0, -1 } }) do
                        if point_in_component(lookup, ox + d[1], oy + d[2]) then
                          touches = true
                          boundary_touches = true
                        end
                      end
                    end
                  end
                end
                if touches then
                  contents[other.kind] = contents[other.kind] + 1
                  table.insert(touching_building_ids, other.id)
                  table.insert(touching_building_kinds, other.kind)
                end
                if boundary_touches then
                  table.insert(boundary_building_ids, other.id)
                  if other.kind == 'door' then
                    table.insert(boundary_door_ids, other.id)
                  end
                end
              end
            end
            local function classify()
              if contents.bed > 0 then return 'bedroom' end
              if contents.workshop > 0 then return 'production' end
              if contents.table > 0 and contents.chair > 0 then return 'dining' end
              return 'enclosed_space'
            end
            local min_x, min_y, max_x, max_y = nil, nil, nil, nil
            local open_tiles = {}
            local open_tile_count = 0
            local interior_tiles = {}
            local boundary_construction_tiles = {}
            local boundary_seen = {}
            local all_boundary_seen = {}
            local boundary_tile_count = 0
            for _, tile in ipairs(tiles) do
              local tx, ty = tile[1], tile[2]
              table.insert(interior_tiles, { tx, ty, bld.z })
              min_x = min_x and math.min(min_x, tx) or tx
              min_y = min_y and math.min(min_y, ty) or ty
              max_x = max_x and math.max(max_x, tx) or tx
              max_y = max_y and math.max(max_y, ty) or ty
              if not completed_building_at(tx, ty, bld.z) then
                open_tile_count = open_tile_count + 1
                if #open_tiles < MAX_ROOM_OPEN_TILE_SAMPLES then
                  table.insert(open_tiles, { tx, ty, bld.z })
                end
              end
              for _, d in ipairs({ { 1, 0 }, { -1, 0 }, { 0, 1 }, { 0, -1 } }) do
                local bx, by = tx + d[1], ty + d[2]
                if not point_in_component(lookup, bx, by) then
                  local boundary_key = bx .. ',' .. by .. ',' .. bld.z
                  if not all_boundary_seen[boundary_key] then
                    all_boundary_seen[boundary_key] = true
                    boundary_tile_count = boundary_tile_count + 1
                  end
                  if completed_construction_tiles[boundary_key]
                      and not boundary_seen[boundary_key] then
                    boundary_seen[boundary_key] = true
                    table.insert(boundary_construction_tiles, { bx, by, bld.z })
                  end
                end
              end
            end
            -- A one-tile furnishing pocket is not a usable room. Furniture is
            -- still traversable interior, so fully furnished multi-tile rooms
            -- remain valid even when no furniture-free floor remains.
            if #tiles >= MIN_ROOM_INTERIOR_TILES then
              table.sort(touching_building_ids)
              table.sort(boundary_building_ids)
              table.sort(boundary_door_ids)
              local accessible, accessibility_complete, accessibility_reason =
                room_accessibility(open_tiles, open_tile_count)
              local signature = table.concat({
                tostring(bld.z), tostring(min_x), tostring(min_y),
                tostring(max_x), tostring(max_y), tostring(#tiles),
                table.concat(touching_building_ids, ','),
              }, ':')
              local space = {
                signature = signature,
                z = bld.z,
                tiles = #tiles,
                kind = classify(),
                contents = contents,
                bounds = { min_x, min_y, max_x, max_y, bld.z },
                interior_tiles = interior_tiles,
                interior_tiles_complete = true,
                boundary_construction_tiles = boundary_construction_tiles,
                boundary_construction_tiles_complete = true,
                boundary_tile_count = boundary_tile_count,
                boundary_tiles_complete = true,
                touching_building_ids = touching_building_ids,
                touching_building_kinds = touching_building_kinds,
                boundary_building_ids = boundary_building_ids,
                boundary_door_ids = boundary_door_ids,
                open_tiles = open_tiles,
                open_tile_count = open_tile_count,
                open_tiles_truncated = open_tile_count > #open_tiles,
                accessible = accessible,
                accessibility_evidence_complete = accessibility_complete,
                accessibility_reason = accessibility_reason,
              }
              if #spaces < MAX_SPACES then
                table.insert(spaces, space)
              else
                spaces_truncated = true
              end
            end
          end
        end
      end
    end
  end
end

local functional = 0
for _, space in ipairs(spaces) do
  if space.kind ~= 'enclosed_space' then
    functional = functional + 1
  end
end

-- Count only visible nearby trunks. Coordinates and cluster centroids are not
-- emitted: the agent must choose targets from visible map evidence instead of
-- receiving runner-selected strategy hints.
local nearby_trees = { total = 0 }
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
  for x = math.max(0, cx - RADIUS), cx + RADIUS do
    for y = math.max(0, cy - RADIUS), cy + RADIUS do
      local block = dfhack.maps.getTileBlock(x, y, cz)
      if block then
        local dx, dy = x % 16, y % 16
        local designation = block.designation[dx][dy]
        local ok_t, is_trunk = pcall(function()
          if not designation or designation.hidden then return false end
          local attr = attrs[block.tiletype[dx][dy]]
          return attr ~= nil and attr.shape == WALL_SHAPE
            and attr.material == TREE_MATERIAL
        end)
        if ok_t and is_trunk then
          nearby_trees.total = nearby_trees.total + 1
        end
      end
    end
  end
end)

-- ASCII minimap of the fort area so the agent can see wall geometry and gaps
-- spatially instead of as coordinate lists. Read-only; bounded to 34x34.
local map_origin = nil
local map_rows = {}
local frozen_liquid_tiles = 0
local access_level_maps = {}
local vertical_access_focus = { active = false }
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
  local map_anchor_buildings = {}
  local anchor_z_counts = {}

  local function map_tile_visible(x, y, z)
    local block = dfhack.maps.getTileBlock(x, y, z)
    if not block then return false end
    local ok, hidden = pcall(function()
      return block.designation[x % 16][y % 16].hidden and true or false
    end)
    return ok and not hidden
  end

  local function visible_building_bounds(bld)
    local min_x, min_y = math.huge, math.huge
    local max_x, max_y = -math.huge, -math.huge
    for bx = bld.x1, bld.x2 do
      for by = bld.y1, bld.y2 do
        if map_tile_visible(bx, by, bld.z) then
          min_x = math.min(min_x, bx)
          min_y = math.min(min_y, by)
          max_x = math.max(max_x, bx)
          max_y = math.max(max_y, by)
        end
      end
    end
    if min_x == math.huge then return nil end
    return { x1 = min_x, y1 = min_y, x2 = max_x, y2 = max_y, z = bld.z }
  end

  -- The room classifier intentionally keeps only furniture and workshops in
  -- `buildings`, but the minimap must follow the visible footprint of every
  -- player building. A farm plot (or another occupied building type) is still
  -- real fort geometry and must keep a distant citizen from pulling the
  -- bounded map window away from the fort. Hidden footprint tiles never
  -- influence the published origin or bounds.
  pcall(function()
    for _, bld in ipairs(df.global.world.buildings.all) do
      local ok_anchor, anchor = pcall(function()
        return visible_building_bounds(bld)
      end)
      if ok_anchor and anchor and anchor.x1 and anchor.y1
          and anchor.x2 and anchor.y2 and anchor.z then
        table.insert(map_anchor_buildings, anchor)
        anchor_z_counts[anchor.z] = (anchor_z_counts[anchor.z] or 0) + 1
      end
    end
  end)

  for _, bld in ipairs(buildings) do
    for fx = bld.x1, bld.x2 do
      for fy = bld.y1, bld.y2 do
        building_tile_kind[fx .. ',' .. fy .. ',' .. bld.z] = bld.kind
      end
    end
  end
  -- citizens anchor the map before any building exists (and are drawn as @)
  local citizen_positions = {}
  local visible_citizen_positions = {}
  pcall(function()
    for _, unit in ipairs(df.global.world.units.active) do
      local ok_c, is_c = pcall(function() return dfhack.units.isCitizen(unit) end)
      if ok_c and is_c and unit.pos then
        local cpos = { x = unit.pos.x, y = unit.pos.y, z = unit.pos.z }
        table.insert(citizen_positions, cpos)
        if map_tile_visible(cpos.x, cpos.y, cpos.z) then
          table.insert(visible_citizen_positions, cpos)
        end
        if #map_anchor_buildings == 0
            and map_tile_visible(cpos.x, cpos.y, cpos.z) then
          anchor_z_counts[unit.pos.z] = (anchor_z_counts[unit.pos.z] or 0) + 1
        end
      end
    end
  end)

  local citizen_tile_lookup = {}
  for _, cpos in ipairs(visible_citizen_positions) do
    citizen_tile_lookup[cpos.x .. ',' .. cpos.y .. ',' .. cpos.z] = true
  end

  local function access_kind_for_shape(shape)
    if shape == STAIR_UP_SHAPE then return 'up_stair' end
    if shape == STAIR_DOWN_SHAPE then return 'down_stair' end
    if shape == STAIR_UPDOWN_SHAPE then return 'up_down_stair' end
    if shape == RAMP_SHAPE then return 'ramp' end
    if shape == RAMP_TOP_SHAPE then return 'ramp_top' end
    return nil
  end

  local function visible_shape_name(shape, hidden)
    if shape == nil or hidden then return false end
    local ok, name = pcall(function() return df.tiletype_shape[shape] end)
    if ok and name then return tostring(name) end
    return tostring(shape)
  end

  local function render_tile(x, y, z)
    local key = x .. ',' .. y .. ',' .. z
    local shape, hidden, material = tile_shape(x, y, z)
    local kind = building_tile_kind[key]
    local access_kind = access_kind_for_shape(shape)
    local ch = ' '
    if shape == nil or hidden then
      ch = ' '
    elseif citizen_tile_lookup[key] then
      ch = '@'
      kind = nil
    elseif kind then
      ch = BUILDING_CHARS[kind] or '?'
    elseif pending_construction_tiles[key] then
      ch = 'x'
    elseif building_at(x, y, z) then
      ch = 'o'
    elseif material == FROZEN_LIQUID_MATERIAL then
      ch = 'i'
    elseif shape == STAIR_UP_SHAPE then
      ch = '<'
    elseif shape == STAIR_DOWN_SHAPE then
      ch = '>'
    elseif shape == STAIR_UPDOWN_SHAPE then
      ch = 'X'
    elseif shape == RAMP_SHAPE or shape == RAMP_TOP_SHAPE then
      ch = '^'
    elseif shape == WALL_SHAPE then
      if construction_set[key] then
        ch = 'W'
      elseif material == TREE_MATERIAL then
        ch = 'T'
      else
        ch = '#'
      end
    elseif shape == FLOOR_SHAPE then
      ch = '.'
    elseif shape == df.tiletype_shape.SHRUB then
      ch = ','
    elseif shape == df.tiletype_shape.SAPLING then
      ch = 's'
    elseif shape == df.tiletype_shape.BOULDER
      or shape == df.tiletype_shape.PEBBLES then
      ch = 'p'
    else
      ch = '~'
    end
    return ch, shape, hidden, material, access_kind
  end

  local anchor_z, best = nil, 0
  for z, count in pairs(anchor_z_counts) do
    if count > best then anchor_z, best = z, count end
  end

  if anchor_z ~= nil then
    local min_x, min_y = math.huge, math.huge
    local max_x, max_y = -math.huge, -math.huge
    for _, bld in ipairs(map_anchor_buildings) do
      if bld.z == anchor_z then
        min_x = math.min(min_x, bld.x1)
        min_y = math.min(min_y, bld.y1)
        max_x = math.max(max_x, bld.x2)
        max_y = math.max(max_y, bld.y2)
      end
    end
    if min_x == math.huge then
      for _, cpos in ipairs(visible_citizen_positions) do
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
      if tonumber(cz) == anchor_z
          and map_tile_visible(tonumber(cx), tonumber(cy), tonumber(cz)) then
        min_x = math.min(min_x, tonumber(cx))
        min_y = math.min(min_y, tonumber(cy))
        max_x = math.max(max_x, tonumber(cx))
        max_y = math.max(max_y, tonumber(cy))
      end
    end
    for key in pairs(pending_construction_tiles) do
      local cx, cy, cz = key:match('(-?%d+),(-?%d+),(-?%d+)')
      if tonumber(cz) == anchor_z
          and map_tile_visible(tonumber(cx), tonumber(cy), tonumber(cz)) then
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

    map_origin = { min_x, min_y, anchor_z }
    for y = min_y, max_y do
      local row = {}
      for x = min_x, max_x do
        local ch, _, hidden, material = render_tile(x, y, anchor_z)
        if not hidden and material == FROZEN_LIQUID_MATERIAL then
          frozen_liquid_tiles = frozen_liquid_tiles + 1
        end
        table.insert(row, ch)
      end
      table.insert(map_rows, table.concat(row))
    end

    if access_focus_rect then
      local fx1, fy1, fz, fx2, fy2 =
        access_focus_rect[1], access_focus_rect[2], access_focus_rect[3],
        access_focus_rect[4], access_focus_rect[5]
      local designated = 0
      local channel_jobs = 0
      local top_visible = 0
      local lower_visible = 0
      local completed_pairs = 0
      local local_step_pairs = 0
      local native_connected_pairs = 0
      local pair_samples = {}
      pcall(function()
        local link = df.global.world.jobs.list.next
        while link do
          local job = link.item
          local name = tostring(df.job_type[job.job_type] or job.job_type)
          local pos = job.pos
          if name == 'DigChannel' and pos and pos.z == fz
              and pos.x >= fx1 and pos.x <= fx2
              and pos.y >= fy1 and pos.y <= fy2 then
            channel_jobs = channel_jobs + 1
          end
          link = link.next
        end
      end)

      -- DFHack 0.47.05 does not expose Maps::canStepBetween to Lua. Mirror
      -- its ordinary diagonal-ramp branch exactly enough to prove the local
      -- edge, then require native canWalkBetween for the specific endpoints.
      -- This prevents an unrelated route elsewhere from satisfying focus.
      local function local_ramp_step(x, y)
        local lower_z = fz - 1
        local lower_block = dfhack.maps.getTileBlock(x, y, lower_z)
        local ramp_top_block = dfhack.maps.getTileBlock(x, y, fz)
        if not lower_block or not ramp_top_block then return false, false end
        local lower_dx, lower_dy = x % 16, y % 16
        local lower_shape, lower_hidden = tile_shape(x, y, lower_z)
        local ramp_top_shape, ramp_top_hidden = tile_shape(x, y, fz)
        if lower_hidden or ramp_top_hidden
            or lower_shape ~= RAMP_SHAPE
            or ramp_top_shape ~= RAMP_TOP_SHAPE then
          return false, false
        end
        local lower_walkable = lower_block.walkable[lower_dx][lower_dy]
        if not lower_walkable or lower_walkable == 0 then return false, false end
        if lower_block.designation[lower_dx][lower_dy].flow_size >= 4 then
          return false, false
        end

        local support_wall = false
        for sx = -1, 1 do
          for sy = -1, 1 do
            if sx ~= 0 or sy ~= 0 then
              local shape, hidden = tile_shape(x + sx, y + sy, lower_z)
              if not hidden and shape == WALL_SHAPE then support_wall = true end
            end
          end
        end
        if not support_wall then return false, false end

        local top_occ = ramp_top_block.occupancy[x % 16][y % 16].building
        if top_occ == df.tile_building_occ.Obstacle
            or top_occ == df.tile_building_occ.Floored
            or top_occ == df.tile_building_occ.Impassable then
          return false, false
        end

        local lower_pos = { x = x, y = y, z = lower_z }
        local valid_local_endpoint = false
        for sx = -1, 1 do
          for sy = -1, 1 do
            if sx ~= 0 or sy ~= 0 then
              local ux, uy = x + sx, y + sy
              local upper_block = dfhack.maps.getTileBlock(ux, uy, fz)
              local upper_shape, upper_hidden = tile_shape(ux, uy, fz)
              if upper_block and upper_shape ~= nil and not upper_hidden then
                local udx, udy = ux % 16, uy % 16
                local upper_walkable = upper_block.walkable[udx][udy]
                local upper_flow = upper_block.designation[udx][udy].flow_size
                if upper_walkable and upper_walkable ~= 0 and upper_flow < 4 then
                  valid_local_endpoint = true
                  local upper_pos = { x = ux, y = uy, z = fz }
                  local ok_pair, pair_connected = pcall(function()
                    return dfhack.maps.canWalkBetween(lower_pos, upper_pos)
                  end)
                  if ok_pair and pair_connected then
                    for _, cpos in ipairs(citizen_positions) do
                      local ok_citizen, citizen_connected = pcall(function()
                        return dfhack.maps.canWalkBetween(cpos, upper_pos)
                      end)
                      if ok_citizen and citizen_connected then return true, true end
                    end
                  end
                end
              end
            end
          end
        end
        return valid_local_endpoint, false
      end

      for x = fx1, fx2 do
        for y = fy1, fy2 do
          local top_shape, top_hidden = tile_shape(x, y, fz)
          local lower_shape, lower_hidden = tile_shape(x, y, fz - 1)
          local top_block = dfhack.maps.getTileBlock(x, y, fz)
          if top_shape ~= nil and not top_hidden then
            top_visible = top_visible + 1
            pcall(function()
              if top_block.designation[x % 16][y % 16].dig
                  == df.tile_dig_designation.Channel then
                designated = designated + 1
              end
            end)
          end
          if lower_shape ~= nil and not lower_hidden then
            lower_visible = lower_visible + 1
          end

          local top_open = top_shape == EMPTY_SHAPE
            or top_shape == RAMP_TOP_SHAPE
            or top_shape == STAIR_DOWN_SHAPE
            or top_shape == STAIR_UPDOWN_SHAPE
          local lower_access = lower_shape == RAMP_SHAPE
            or lower_shape == STAIR_UP_SHAPE
            or lower_shape == STAIR_UPDOWN_SHAPE
          local geometry_complete = not top_hidden and not lower_hidden
            and top_open and lower_access
          local local_step_valid = false
          local connected = false
          if geometry_complete then
            completed_pairs = completed_pairs + 1
            local_step_valid, connected = local_ramp_step(x, y)
            if local_step_valid then local_step_pairs = local_step_pairs + 1 end
            if connected then
              native_connected_pairs = native_connected_pairs + 1
            end
          end
          if #pair_samples < 16 then
            table.insert(pair_samples, {
              x = x,
              y = y,
              top_z = fz,
              lower_z = fz - 1,
              top_visible = top_shape ~= nil and not top_hidden,
              lower_visible = lower_shape ~= nil and not lower_hidden,
              top_shape = visible_shape_name(top_shape, top_hidden),
              lower_shape = visible_shape_name(lower_shape, lower_hidden),
              geometry_complete = geometry_complete,
              local_step_valid = local_step_valid,
              native_connected = connected,
            })
          end
        end
      end

      local status = 'unknown'
      if designated > 0 or channel_jobs > 0 then
        status = 'pending'
      elseif native_connected_pairs > 0 then
        status = 'connected'
      elseif top_visible > 0 and lower_visible > 0 then
        status = 'failed'
      end
      vertical_access_focus = {
        active = true,
        source = 'model_owned_channel_tile',
        rect = access_focus_rect,
        status = status,
        channel_designations = designated,
        channel_jobs = channel_jobs,
        top_visible_tiles = top_visible,
        lower_visible_tiles = lower_visible,
        completed_geometry_pairs = completed_pairs,
        local_step_pairs = local_step_pairs,
        native_connected_pairs = native_connected_pairs,
        pair_samples = pair_samples,
      }

      local center_x = math.floor((fx1 + fx2) / 2)
      local center_y = math.floor((fy1 + fy2) / 2)
      local radius = 8
      local level_x1 = math.max(0, center_x - radius)
      local level_y1 = math.max(0, center_y - radius)
      local level_x2 = level_x1 + radius * 2
      local level_y2 = level_y1 + radius * 2
      for _, level_z in ipairs({ fz, fz - 1 }) do
        if level_z >= 0 then
          local rows = {}
          local visible_tiles = 0
          for y = level_y1, level_y2 do
            local row = {}
            for x = level_x1, level_x2 do
              local ch, shape, hidden = render_tile(x, y, level_z)
              if shape ~= nil and not hidden then visible_tiles = visible_tiles + 1 end
              table.insert(row, ch)
            end
            table.insert(rows, table.concat(row))
          end
          table.insert(access_level_maps, {
            z = level_z,
            origin = { level_x1, level_y1, level_z },
            center = { center_x, center_y, level_z },
            source_action_rect = access_focus_rect,
            visible_tiles = visible_tiles,
            rows = rows,
          })
        end
      end
    end
  end
end

print(json.encode({
  ok = true,
  enclosed_spaces = #spaces,
  functional_rooms = functional,
  spaces = spaces,
  spaces_limit = MAX_SPACES,
  spaces_truncated = spaces_truncated,
  component_scan_truncated = component_scan_truncated,
  building_scan_complete = building_scan_complete,
  raw_construction_records = raw_construction_records,
  constructions = constructions,
  construction_tiles = construction_tiles,
  construction_details = construction_details,
  construction_tiles_complete = construction_tiles_complete,
  pending_constructions = pending_constructions,
  nearby_trees = nearby_trees,
  player_buildings = #buildings,
  frozen_liquid_tiles = frozen_liquid_tiles,
  vertical_access_focus = vertical_access_focus,
  access_level_maps = access_level_maps,
  map_origin = map_origin,
  map_rows = map_rows,
}))
