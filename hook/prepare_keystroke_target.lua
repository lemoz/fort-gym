-- prepare_keystroke_target.lua: center the UI on a visible mineable wall pocket.

local json = require('json')

local SELECT_OFFSET_X1 = 7
local SELECT_OFFSET_Y1 = 9
local SELECT_WIDTH = 4
local SELECT_HEIGHT = 2
local MIN_DESIGNATABLE_TILES = 4
local Z_SEARCH_RADIUS = 6

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
  return attr and attr.shape == df.tiletype_shape.WALL
end

local function count_designatable(x1, y1, z)
  local count = 0
  for tx = x1, x1 + SELECT_WIDTH - 1 do
    for ty = y1, y1 + SELECT_HEIGHT - 1 do
      if valid_wall_tile(tx, ty, z) then
        count = count + 1
      end
    end
  end
  return count
end

local function candidate_payload(x1, y1, z, count)
  local window_x = math.max(0, x1 - SELECT_OFFSET_X1)
  local window_y = math.max(0, y1 - SELECT_OFFSET_Y1)
  df.global.window_x = window_x
  df.global.window_y = window_y
  df.global.window_z = z
  df.global.cursor.x = -30000
  df.global.cursor.y = -30000
  df.global.cursor.z = -30000

  return {
    ok = true,
    source = 'visible_mineable_wall',
    target_rect = { window_x, window_y, z, window_x + 14, window_y + 14, z },
    selection_rect = { x1, y1, z, x1 + SELECT_WIDTH - 1, y1 + SELECT_HEIGHT - 1, z },
    designatable_tiles = count,
    window_x = window_x,
    window_y = window_y,
    window_z = z,
    expected_cursor_after_designate = { window_x + 11, window_y + 11, z },
    recommended_keys = {
      'D_DESIGNATE',
      'DESIGNATE_DIG',
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
    },
  }
end

local function try_candidate(x1, y1, z)
  if x1 < 0 or y1 < 0 or z < 0 then
    return nil
  end
  local count = count_designatable(x1, y1, z)
  if count >= MIN_DESIGNATABLE_TILES then
    return candidate_payload(x1, y1, z, count)
  end
  return nil
end

local function search_near_window()
  local window_x = df.global.window_x or 0
  local window_y = df.global.window_y or 0
  local window_z = df.global.window_z or 0
  for dz = -Z_SEARCH_RADIUS, Z_SEARCH_RADIUS do
    local z = window_z + dz
    for x1 = math.max(0, window_x - 80), window_x + 120 do
      for y1 = math.max(0, window_y - 80), window_y + 120 do
        local payload = try_candidate(x1, y1, z)
        if payload then
          return payload
        end
      end
    end
  end
  return nil
end

local function search_loaded_map()
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
          local payload = try_candidate(x1, y1, z)
          if payload then
            return payload
          end
        end
      end
    end
  end

  return nil
end

local payload = search_near_window() or search_loaded_map()
if payload then
  print(json.encode(payload))
else
  print(json.encode({ ok = false, error = 'no_visible_mineable_wall_target' }))
end
