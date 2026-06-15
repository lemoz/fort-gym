-- complete_dig_rect.lua: bounded DFHack completion for designated wall tiles.

local json = require('json')
local args = {...}

local function to_int(v)
  local n = tonumber(v)
  if not n then return nil end
  return math.floor(n)
end

local x1 = to_int(args[1])
local y1 = to_int(args[2])
local z1 = to_int(args[3])
local x2 = to_int(args[4])
local y2 = to_int(args[5])
local z2 = to_int(args[6])

if not (x1 and y1 and z1 and x2 and y2 and z2) or z1 ~= z2 then
  print(json.encode({ ok = false, error = 'bad_rect' }))
  return
end

local rx1, ry1, rz = math.min(x1, x2), math.min(y1, y2), z1
local rx2, ry2 = math.max(x1, x2), math.max(y1, y2)

if (rx2 - rx1 + 1) > 30 or (ry2 - ry1 + 1) > 30 then
  print(json.encode({ ok = false, error = 'rect_too_large' }))
  return
end

local region = df.global.world.map
if not region or not region.map_blocks then
  print(json.encode({ ok = false, error = 'map_unavailable' }))
  return
end

local attrs = df.tiletype.attrs
local floor_shape = df.tiletype_shape.FLOOR
local wall_shape = df.tiletype_shape.WALL
local no_dig = df.tile_dig_designation.No
local sx = region.x_count_block
local sy = region.y_count_block
local block_count = #region.map_blocks

local function floor_for(attr)
  local fallback = nil
  for tiletype, candidate in ipairs(attrs) do
    if candidate and candidate.shape == floor_shape then
      fallback = fallback or tiletype
      if candidate.material == attr.material and candidate.special == attr.special then
        return tiletype
      end
    end
  end
  return fallback
end

local changed = 0
local skipped_non_designated = 0
local skipped_non_wall = 0
local missing_blocks = 0

for tx = rx1, rx2 do
  for ty = ry1, ry2 do
    local bx = math.floor(tx / 16)
    local by = math.floor(ty / 16)
    local index = bx + by * sx + rz * sx * sy
    local block = nil
    if bx >= 0 and by >= 0 and bx < sx and by < sy and index >= 0 and index < block_count then
      block = region.map_blocks[index]
    end
    if block then
      local dx = tx % 16
      local dy = ty % 16
      local designation = block.designation[dx][dy]
      local tiletype = block.tiletype[dx][dy]
      local attr = attrs[tiletype]
      if not designation or designation.dig == no_dig then
        skipped_non_designated = skipped_non_designated + 1
      elseif not attr or attr.shape ~= wall_shape then
        skipped_non_wall = skipped_non_wall + 1
        designation.dig = no_dig
      else
        local floor_tiletype = floor_for(attr)
        if floor_tiletype then
          block.tiletype[dx][dy] = floor_tiletype
          designation.dig = no_dig
          designation.hidden = false
          block.flags.designated = true
          dfhack.maps.enableBlockUpdates(block)
          changed = changed + 1
        else
          skipped_non_wall = skipped_non_wall + 1
        end
      end
    else
      missing_blocks = missing_blocks + 1
    end
  end
end

print(json.encode({
  ok = true,
  kind = 'complete_dig',
  rect = { rx1, ry1, rz, rx2, ry2, rz },
  changed = changed,
  skipped_non_designated = skipped_non_designated,
  skipped_non_wall = skipped_non_wall,
  missing_blocks = missing_blocks,
}))
