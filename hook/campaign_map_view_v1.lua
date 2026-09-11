-- Read-only, model-selected terrain window. No block allocation or game writes.
-- getTileSize is in tiles; getSize would incorrectly return block dimensions.
-- https://docs.dfhack.org/en/0.47.05-r7/docs/Lua%20API.html#maps-module
local json = require('json')
local args = {...}
local result = {
  schema_version = 'fortgym.campaign-map-view/v1',
  ok = false,
  active = false,
  scope = 'visible_terrain_only',
}
local function emit(error)
  result.error = error
  print(json.encode(result))
end
local function integer(value)
  return type(value) == 'number' and value == value
    and value ~= math.huge and value ~= -math.huge and value == math.floor(value)
end
local ok, sx, sy, sz = pcall(dfhack.maps.getTileSize)
if not ok or not integer(sx) or not integer(sy) or not integer(sz)
    or sx <= 0 or sy <= 0 or sz <= 0 then
  emit('map_dimensions_unavailable')
  return
end
result.map_dimensions = {sx, sy, sz}
result.year = df.global.cur_year
result.year_tick = df.global.cur_year_tick
result.paused = df.global.pause_state
if result.paused ~= true or not integer(result.year) or result.year < 0
    or not integer(result.year_tick) or result.year_tick < 0
    or result.year_tick >= 403200 then
  emit('paused_calendar_unavailable')
  return
end
if #args == 0 then
  result.ok = true
  emit()
  return
end
if #args ~= 5 then
  emit('view_requires_x_y_z_width_height')
  return
end
local x, y, z, width, height =
  tonumber(args[1]), tonumber(args[2]), tonumber(args[3]), tonumber(args[4]), tonumber(args[5])
if not integer(x) or not integer(y) or not integer(z)
    or not integer(width) or not integer(height)
    or x < 0 or y < 0 or z < 0
    or width < 1 or width > 34 or height < 1 or height > 34 then
  emit('view_parameters_out_of_bounds')
  return
end
if x + width > sx or y + height > sy or z >= sz then
  emit('view_rectangle_outside_map')
  return
end

local shapes = df.tiletype_shape
local materials = df.tiletype_material
local glyphs = {
  [shapes.FLOOR] = '.', [shapes.WALL] = '#',
  [shapes.STAIR_UP] = '<', [shapes.STAIR_DOWN] = '>',
  [shapes.STAIR_UPDOWN] = 'X', [shapes.RAMP] = '^',
  [shapes.RAMP_TOP] = '^', [shapes.EMPTY] = '~',
  [shapes.SHRUB] = ',', [shapes.SAPLING] = 's',
  [shapes.BOULDER] = 'p', [shapes.PEBBLES] = 'p',
}
local visible, hidden, unreadable = 0, 0, 0
local function read_tile(tx, ty)
  local read_ok, glyph, is_hidden = pcall(function()
    local block = dfhack.maps.getTileBlock(tx, ty, z)
    if not block then error('unallocated') end
    local designation = block.designation[tx % 16][ty % 16]
    if type(designation.hidden) ~= 'boolean' then error('visibility_unavailable') end
    -- Read no tile type, material or liquid detail before the visibility check.
    if designation.hidden then return ' ', true end
    local attr = df.tiletype.attrs[block.tiletype[tx % 16][ty % 16]]
    if not attr or attr.shape == nil or attr.material == nil then error('tile_unreadable') end
    if attr.material == materials.FROZEN_LIQUID then return 'i', false end
    if designation.flow_size and designation.flow_size > 0 then
      return designation.liquid_type and 'L' or 'w', false
    end
    if attr.shape == shapes.WALL and attr.material == materials.TREE then return 'T', false end
    return glyphs[attr.shape] or '?', false
  end)
  if not read_ok then
    unreadable = unreadable + 1
    return ' '
  end
  if is_hidden then hidden = hidden + 1 else visible = visible + 1 end
  return glyph
end

local rows = {}
for ty = y, y + height - 1 do
  local row = {}
  for tx = x, x + width - 1 do table.insert(row, read_tile(tx, ty)) end
  table.insert(rows, table.concat(row))
end
result.ok = true
result.active = true
result.map_origin = {x, y, z}
result.map_size = {width, height}
result.map_rows = rows
result.visible_tiles = visible
result.hidden_tiles = hidden
result.unreadable_tiles = unreadable
result.scan_complete = unreadable == 0
result.legend = 'Terrain only: blank=hidden/unreadable; .=floor; #=wall; T=tree; '
  .. '<=up stair; >=down stair; X=up/down stair; ^=ramp; ~=open space; '
  .. ',=shrub; s=sapling; p=loose rock; i=frozen liquid; w=water; L=magma; ?=other terrain. '
  .. 'No units, buildings, items or pathfinding are shown.'
emit()
