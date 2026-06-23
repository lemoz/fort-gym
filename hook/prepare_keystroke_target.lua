-- prepare_keystroke_target.lua: center the UI on a reachable target for native UI play.

local json = require('json')
local args = {...}

local MODE = args[1] or 'starter'

local SELECT_OFFSET_X1 = 7
local SELECT_OFFSET_Y1 = 9
local SELECT_WIDTH = 4
local SELECT_HEIGHT = 2
local MIN_DESIGNATABLE_TILES = 4
local MIN_MATERIAL_TILES = 1
local MIN_CITIZEN_NEAR_TILES = 1
local CITIZEN_SEARCH_RADIUS = 25
local Z_SEARCH_RADIUS = 6
local STONE_MATERIALS = {
  [2] = true, -- stone wall
  [3] = true, -- feature stone wall
  [5] = true, -- mineral/vein wall
}

local function valid_wall_tile(tx, ty, tz)
  local block = dfhack.maps.getTileBlock(tx, ty, tz)
  if not block then
    return false
  end

  local dx = tx % 16
  local dy = ty % 16
  local designation = block.designation[dx][dy]
  if not designation or designation.hidden or designation.dig ~= df.tile_dig_designation.No then
    return false
  end

  local attr = df.tiletype.attrs[block.tiletype[dx][dy]]
  local caption = attr and tostring(attr.caption or '') or ''
  return attr and attr.shape == df.tiletype_shape.WALL and not caption:find('trunk')
end

local function valid_material_wall_tile(tx, ty, tz)
  local block = dfhack.maps.getTileBlock(tx, ty, tz)
  if not block then
    return false
  end

  local dx = tx % 16
  local dy = ty % 16
  local designation = block.designation[dx][dy]
  local occupancy = block.occupancy[dx][dy]
  if not designation or designation.hidden or designation.dig ~= df.tile_dig_designation.No then
    return false
  end
  if occupancy and occupancy.building ~= 0 then
    return false
  end

  local attr = df.tiletype.attrs[block.tiletype[dx][dy]]
  if not attr or attr.shape ~= df.tiletype_shape.WALL then
    return false
  end

  local caption = string.lower(tostring(attr.caption or ''))
  if caption:find('trunk') or caption:find('root') or caption:find('cap ') then
    return false
  end

  local material = tonumber(attr.material)
  return STONE_MATERIALS[material] or caption:find('stone wall') or caption:find('vein wall')
end

local function valid_floor_tile(tx, ty, tz)
  local block = dfhack.maps.getTileBlock(tx, ty, tz)
  if not block then
    return false
  end

  local dx = tx % 16
  local dy = ty % 16
  local designation = block.designation[dx][dy]
  local occupancy = block.occupancy[dx][dy]
  if not designation or designation.hidden or designation.dig ~= df.tile_dig_designation.No then
    return false
  end
  if occupancy and occupancy.building ~= 0 then
    return false
  end

  local attr = df.tiletype.attrs[block.tiletype[dx][dy]]
  return attr and attr.shape == df.tiletype_shape.FLOOR
end

local function count_designatable(x1, y1, z, valid_fn)
  local count = 0
  for tx = x1, x1 + SELECT_WIDTH - 1 do
    for ty = y1, y1 + SELECT_HEIGHT - 1 do
      if valid_fn(tx, ty, z) then
        count = count + 1
      end
    end
  end
  return count
end

local function candidate_payload(x1, y1, z, count, source, designation_key, target_mode)
  designation_key = designation_key or 'DESIGNATE_DIG'
  target_mode = target_mode or MODE
  local window_x = math.max(0, x1 - SELECT_OFFSET_X1)
  local window_y = math.max(0, y1 - SELECT_OFFSET_Y1)
  df.global.window_x = window_x
  df.global.window_y = window_y
  df.global.window_z = z
  df.global.cursor.x = window_x + 11
  df.global.cursor.y = window_y + 11
  df.global.cursor.z = z

  return {
    ok = true,
    source = source or 'visible_mineable_wall',
    target_mode = target_mode,
    designation_key = designation_key,
    target_rect = { window_x, window_y, z, window_x + 14, window_y + 14, z },
    selection_rect = { x1, y1, z, x1 + SELECT_WIDTH - 1, y1 + SELECT_HEIGHT - 1, z },
    designatable_tiles = count,
    window_x = window_x,
    window_y = window_y,
    window_z = z,
    expected_cursor_after_designate = { window_x + 11, window_y + 11, z },
    recommended_keys = {
      'D_DESIGNATE',
      designation_key,
      'CURSOR_LEFT',
      'CURSOR_LEFT',
      'CURSOR_LEFT',
      'CURSOR_LEFT',
      'CURSOR_UP',
      'CURSOR_UP',
      'SELECT',
      'CURSOR_RIGHT',
      'CURSOR_RIGHT',
      'CURSOR_RIGHT',
      'CURSOR_DOWN',
      'SELECT',
      'LEAVESCREEN',
    },
  }
end

local function try_candidate(x1, y1, z, min_tiles, source, valid_fn, designation_key, target_mode)
  if x1 < 0 or y1 < 0 or z < 0 then
    return nil
  end
  local count = count_designatable(x1, y1, z, valid_fn or valid_wall_tile)
  if count >= (min_tiles or MIN_DESIGNATABLE_TILES) then
    return candidate_payload(x1, y1, z, count, source, designation_key, target_mode)
  end
  return nil
end

local function search_near_citizens(valid_fn, source, designation_key, min_tiles, target_mode)
  if not df.global.world.units or not df.global.world.units.active then
    return nil
  end

  for _, unit in ipairs(df.global.world.units.active) do
    if dfhack.units.isCitizen(unit) and not dfhack.units.isDead(unit) and unit.pos then
      local z = unit.pos.z
      for radius = 1, CITIZEN_SEARCH_RADIUS do
        for x1 = math.max(0, unit.pos.x - radius), unit.pos.x + radius do
          for y1 = math.max(0, unit.pos.y - radius), unit.pos.y + radius do
            local payload = try_candidate(
              x1,
              y1,
              z,
              min_tiles or MIN_CITIZEN_NEAR_TILES,
              source,
              valid_fn,
              designation_key,
              target_mode
            )
            if payload then
              payload.nearest_citizen = { unit.pos.x, unit.pos.y, unit.pos.z }
              payload.nearest_citizen_radius = radius
              return payload
            end
          end
        end
      end
    end
  end

  return nil
end

local function search_near_window(valid_fn, source, designation_key, min_tiles, target_mode)
  local window_x = df.global.window_x or 0
  local window_y = df.global.window_y or 0
  local window_z = df.global.window_z or 0
  for dz = -Z_SEARCH_RADIUS, Z_SEARCH_RADIUS do
    local z = window_z + dz
    for x1 = math.max(0, window_x - 80), window_x + 120 do
      for y1 = math.max(0, window_y - 80), window_y + 120 do
        local payload = try_candidate(
          x1,
          y1,
          z,
          min_tiles or MIN_DESIGNATABLE_TILES,
          source or 'window_visible_mineable_wall',
          valid_fn or valid_wall_tile,
          designation_key or 'DESIGNATE_DIG',
          target_mode
        )
        if payload then
          return payload
        end
      end
    end
  end
  return nil
end

local function search_loaded_map(valid_fn, source, designation_key, min_tiles, target_mode)
  local map = df.global.world.map
  if not map or not map.map_blocks then
    return nil
  end

  local window_z = df.global.window_z or 0
  for _, block in ipairs(map.map_blocks) do
    local z = block.map_pos.z
    if math.abs(z - window_z) <= Z_SEARCH_RADIUS then
      for dx = 0, 15 do
        for dy = 0, 15 do
          local x1 = block.map_pos.x + dx
          local y1 = block.map_pos.y + dy
          local payload = try_candidate(
            x1,
            y1,
            z,
            min_tiles or MIN_DESIGNATABLE_TILES,
            source or 'loaded_map_visible_mineable_wall',
            valid_fn or valid_wall_tile,
            designation_key or 'DESIGNATE_DIG',
            target_mode
          )
          if payload then
            return payload
          end
        end
      end
    end
  end

  return nil
end

local function material_payload()
  local payload = search_near_citizens(
    valid_material_wall_tile,
    'citizen_near_visible_stone_material_wall',
    'DESIGNATE_DIG',
    MIN_MATERIAL_TILES,
    'material'
  ) or search_near_window(
    valid_material_wall_tile,
    'window_visible_stone_material_wall',
    'DESIGNATE_DIG',
    MIN_MATERIAL_TILES,
    'material'
  )
  if payload then
    payload.material_goal = 'mine visible stone/vein wall through the native designation UI'
  end
  return payload
end

local function starter_payload()
  return search_near_citizens(
    valid_floor_tile,
    'citizen_near_visible_floor_stair_down',
    'DESIGNATE_STAIR_DOWN',
    MIN_DESIGNATABLE_TILES,
    'starter'
  ) or search_near_citizens(
    valid_wall_tile,
    'citizen_near_visible_mineable_wall',
    'DESIGNATE_DIG',
    MIN_CITIZEN_NEAR_TILES,
    'starter'
  ) or search_near_window(
    valid_wall_tile,
    'window_visible_mineable_wall',
    'DESIGNATE_DIG',
    MIN_DESIGNATABLE_TILES,
    'starter'
  ) or search_loaded_map(
    valid_wall_tile,
    'loaded_map_visible_mineable_wall',
    'DESIGNATE_DIG',
    MIN_DESIGNATABLE_TILES,
    'starter'
  )
end

local payload = nil
if MODE == 'material' then
  payload = material_payload()
else
  payload = starter_payload()
end
if payload then
  print(json.encode(payload))
else
  print(json.encode({ ok = false, mode = MODE, error = 'no_visible_target' }))
end
