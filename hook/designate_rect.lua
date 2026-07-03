-- designate_rect.lua: safely designate dig/channel rectangles or trigger chop.

local json = require('json')
local args = {...}

local kind = tostring(args[1] or '')
local valid = { dig = true, channel = true, chop = true }
if not valid[kind] then
  print(json.encode({ ok = false, error = 'invalid_kind' }))
  return
end

local function to_int(v)
  local n = tonumber(v)
  if not n then return nil end
  return math.floor(n)
end

local x1 = to_int(args[2])
local y1 = to_int(args[3])
local z1 = to_int(args[4])
local x2 = to_int(args[5])
local y2 = to_int(args[6])
local z2 = to_int(args[7])

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

if kind == 'chop' then
  dfhack.run_script('autochop', 'now')
  print(json.encode({ ok = true, kind = kind }))
  return
end

local block_w, block_h = 16, 16

local attrs = df.tiletype.attrs
local wall_shape = df.tiletype_shape.WALL

local function target_designation(mode)
  if mode == 'dig' then
    return df.tile_dig_designation.Default
  elseif mode == 'channel' then
    return df.tile_dig_designation.Channel
  end
  return nil
end

local function is_wall_tile(block, dx, dy)
  local ok, result = pcall(function()
    local tiletype = block.tiletype[dx][dy]
    local attr = attrs[tiletype]
    return attr ~= nil and attr.shape == wall_shape
  end)
  if not ok then return nil end
  return result
end

-- Classifies and writes a single tile, returning a status string:
-- 'missing', 'already_designated', 'non_wall_tiles', or 'newly_designated'.
local function set_tile(x, y, z, mode)
  local region = df.global.world.map
  local bx, by = math.floor(x / block_w), math.floor(y / block_h)
  local sx = region.x_count_block
  local sy = region.y_count_block
  if bx < 0 or by < 0 or bx >= sx or by >= sy then return 'missing' end

  local index = bx + by * sx + z * sx * sy
  if index < 0 or index >= #region.map_blocks then return 'missing' end
  local block = region.map_blocks[index]
  if not block then return 'missing' end

  local dx, dy = x % block_w, y % block_h
  local designation = block.designation[dx][dy]
  local target = target_designation(mode)
  local status
  if designation.dig == target then
    status = 'already_designated'
  else
    local wall = is_wall_tile(block, dx, dy)
    if wall == false then
      status = 'non_wall_tiles'
    else
      status = 'newly_designated'
    end
  end

  designation.dig = target
  block.flags.designated = true
  return status
end

local newly_designated = 0
local already_designated = 0
local non_wall_tiles = 0
local missing_tiles = 0

for tx = rx1, rx2 do
  for ty = ry1, ry2 do
    local status = set_tile(tx, ty, rz, kind)
    if status == 'missing' then
      missing_tiles = missing_tiles + 1
    elseif status == 'already_designated' then
      already_designated = already_designated + 1
    elseif status == 'non_wall_tiles' then
      non_wall_tiles = non_wall_tiles + 1
    elseif status == 'newly_designated' then
      newly_designated = newly_designated + 1
    end
  end
end

print(json.encode({
  ok = true,
  kind = kind,
  rect = { rx1, ry1, rz, rx2, ry2, rz },
  newly_designated = newly_designated,
  already_designated = already_designated,
  non_wall_tiles = non_wall_tiles,
  missing_tiles = missing_tiles,
}))
