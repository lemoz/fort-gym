-- map_snapshot.lua: bounded map-tile capture for saved run replay proof.

local json = require('json')
local args = {...}

local function to_int(v, default)
  local n = tonumber(v)
  if not n then return default end
  return math.floor(n)
end

local x1 = to_int(args[1], 50)
local y1 = to_int(args[2], 35)
local z1 = to_int(args[3], 0)
local x2 = to_int(args[4], 62)
local y2 = to_int(args[5], 39)
local z2 = to_int(args[6], z1)

if z1 ~= z2 then
  print(json.encode({ ok = false, error = 'z_span_not_supported' }))
  return
end

local rx1, ry1, rz = math.min(x1, x2), math.min(y1, y2), z1
local rx2, ry2 = math.max(x1, x2), math.max(y1, y2)

if (rx2 - rx1 + 1) > 64 or (ry2 - ry1 + 1) > 64 then
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

local function tile_key(tx, ty)
  return tostring(tx) .. ',' .. tostring(ty)
end

local building_tiles = {}
local buildings = df.global.world.buildings and df.global.world.buildings.all
if buildings then
  pcall(function()
    local carpenter_type = nil
    if df.workshop_type then
      carpenter_type = df.workshop_type.Carpenters or df.workshop_type.Carpenter
    end
    for _, building in ipairs(buildings) do
      if building.z == rz
          and building.x2 >= rx1 and building.x1 <= rx2
          and building.y2 >= ry1 and building.y1 <= ry2 then
        local is_workshop = false
        local ok_type, building_type = pcall(function() return building:getType() end)
        local building_type_name = ok_type and tostring(building_type) or 'building'
        if ok_type and building_type == df.building_type.Workshop then
          is_workshop = true
        end
        local ok_instance, is_instance = pcall(function()
          return df.building_workshopst and df.building_workshopst:is_instance(building)
        end)
        if ok_instance and is_instance then
          is_workshop = true
        end

        local ok_workshop_type, workshop_type = pcall(function() return building.type end)
        local workshop_type_name = ok_workshop_type and tostring(workshop_type) or ''
        local is_carpenter = (ok_workshop_type and carpenter_type and workshop_type == carpenter_type)
            or workshop_type_name == 'Carpenters'
            or workshop_type_name == 'Carpenter'

        for tx = math.max(rx1, building.x1), math.min(rx2, building.x2) do
          for ty = math.max(ry1, building.y1), math.min(ry2, building.y2) do
            building_tiles[tile_key(tx, ty)] = {
              kind = is_workshop and 'workshop' or 'building',
              name = is_carpenter and 'CarpenterWorkshop' or building_type_name,
              char = is_carpenter and 'C' or 'B',
            }
          end
        end
      end
    end
  end)
end

local tiles = {}
local floor_tiles = 0
local wall_tiles = 0
local hidden_tiles = 0
local dig_designations = 0
local missing_blocks = 0
local building_tile_count = 0

for ty = ry1, ry2 do
  for tx = rx1, rx2 do
    local tile = {
      x = tx,
      y = ty,
      z = rz,
      category = 'missing',
      char = ' ',
      hidden = false,
      dig = 'No',
    }

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
      tile.tiletype = tonumber(tiletype) or -1
      tile.tiletype_name = tostring(tiletype)

      if designation then
        tile.hidden = designation.hidden and true or false
        tile.dig = tostring(designation.dig)
        if designation.hidden then
          hidden_tiles = hidden_tiles + 1
        end
        if designation.dig ~= no_dig then
          dig_designations = dig_designations + 1
        end
      end

      if attr and attr.shape == floor_shape then
        tile.category = 'floor'
        tile.shape = 'FLOOR'
        tile.char = '.'
        floor_tiles = floor_tiles + 1
      elseif attr and attr.shape == wall_shape then
        tile.category = 'wall'
        tile.shape = 'WALL'
        tile.char = '#'
        wall_tiles = wall_tiles + 1
      else
        tile.category = 'other'
        tile.shape = attr and tostring(attr.shape) or 'unknown'
        tile.char = ','
      end

      if tile.hidden then
        tile.category = 'hidden'
        tile.char = '?'
      elseif designation and designation.dig ~= no_dig then
        tile.category = 'dig'
        tile.char = 'x'
      end

      local building = building_tiles[tile_key(tx, ty)]
      if building then
        tile.category = 'building'
        tile.char = building.char
        tile.building = building.name
        tile.building_kind = building.kind
        building_tile_count = building_tile_count + 1
      end
    else
      missing_blocks = missing_blocks + 1
    end

    table.insert(tiles, tile)
  end
end

print(json.encode({
  ok = true,
  source = 'dfhack-map',
  rect = { rx1, ry1, rz, rx2, ry2, rz },
  width = rx2 - rx1 + 1,
  height = ry2 - ry1 + 1,
  z = rz,
  window_z = df.global.window_z or 0,
  floor_tiles = floor_tiles,
  wall_tiles = wall_tiles,
  hidden_tiles = hidden_tiles,
  dig_designations = dig_designations,
  missing_blocks = missing_blocks,
  building_tiles = building_tile_count,
  tiles = tiles,
}))
