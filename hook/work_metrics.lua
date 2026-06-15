-- work_metrics.lua: bounded work/progress metrics for a target dig rectangle.

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
local x2 = to_int(args[4], 54)
local y2 = to_int(args[5], 39)
local z2 = to_int(args[6], z1)

if z1 ~= z2 then
  print(json.encode({ ok = false, error = 'z_span_not_supported' }))
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

local target_tiles = 0
local target_dig_designations = 0
local target_floor_tiles = 0
local target_wall_tiles = 0
local target_hidden_tiles = 0
local target_visible_tiles = 0
local target_missing_blocks = 0
local sx = region.x_count_block
local sy = region.y_count_block
local block_count = #region.map_blocks

for tx = rx1, rx2 do
  for ty = ry1, ry2 do
    target_tiles = target_tiles + 1
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
      if designation and designation.dig ~= no_dig then
        target_dig_designations = target_dig_designations + 1
      end
      if designation and designation.hidden then
        target_hidden_tiles = target_hidden_tiles + 1
      elseif designation then
        target_visible_tiles = target_visible_tiles + 1
      end

      local tiletype = block.tiletype[dx][dy]
      local attr = attrs[tiletype]
      if attr then
        if attr.shape == floor_shape then
          target_floor_tiles = target_floor_tiles + 1
        elseif attr.shape == wall_shape then
          target_wall_tiles = target_wall_tiles + 1
        end
      end
    else
      target_missing_blocks = target_missing_blocks + 1
    end
  end
end

local active_jobs = 0
local active_dig_jobs = 0
if df.global.world.jobs and df.global.world.jobs.list then
  for _, job in ipairs(df.global.world.jobs.list) do
    active_jobs = active_jobs + 1
    if job.job_type == df.job_type.Dig then
      active_dig_jobs = active_dig_jobs + 1
    end
  end
end

local citizens_total = 0
local miners_total = 0
local citizens_on_target_z = 0
if df.global.world.units and df.global.world.units.active then
  for _, unit in ipairs(df.global.world.units.active) do
    if dfhack.units.isCitizen(unit) and not dfhack.units.isDead(unit) then
      citizens_total = citizens_total + 1
      if unit.pos and unit.pos.z == rz then
        citizens_on_target_z = citizens_on_target_z + 1
      end
      if unit.status and unit.status.labors then
        for labor, enabled in pairs(unit.status.labors) do
          if enabled and tostring(labor) == 'MINE' then
            miners_total = miners_total + 1
            break
          end
        end
      end
    end
  end
end

print(json.encode({
  ok = true,
  target_rect = { rx1, ry1, rz, rx2, ry2, rz },
  target_z = rz,
  window_z = df.global.window_z or 0,
  target_tiles = target_tiles,
  target_dig_designations = target_dig_designations,
  target_floor_tiles = target_floor_tiles,
  target_wall_tiles = target_wall_tiles,
  target_hidden_tiles = target_hidden_tiles,
  target_visible_tiles = target_visible_tiles,
  target_missing_blocks = target_missing_blocks,
  active_jobs = active_jobs,
  active_dig_jobs = active_dig_jobs,
  citizens_total = citizens_total,
  miners_total = miners_total,
  citizens_on_target_z = citizens_on_target_z,
}))
