-- work_metrics.lua: bounded work/progress metrics for a target dig rectangle.

local json = require('json')
local args = {...}
local global_only = tostring(args[1] or '') == 'global'

local function to_int(v, default)
  local n = tonumber(v)
  if not n then return default end
  return math.floor(n)
end

local x1 = global_only and 0 or to_int(args[1], 50)
local y1 = global_only and 0 or to_int(args[2], 35)
local z1 = global_only and 0 or to_int(args[3], 0)
local x2 = global_only and 0 or to_int(args[4], 54)
local y2 = global_only and 0 or to_int(args[5], 39)
local z2 = global_only and 0 or to_int(args[6], z1)
local window_x = df.global.window_x or 0
local window_y = df.global.window_y or 0
local window_z = df.global.window_z or 0
local cursor_x = df.global.cursor and df.global.cursor.x or -30000
local cursor_y = df.global.cursor and df.global.cursor.y or -30000
local cursor_z = df.global.cursor and df.global.cursor.z or -30000

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
if not global_only and (not region or not region.map_blocks) then
  print(json.encode({ ok = false, error = 'map_unavailable' }))
  return
end

local attrs = df.tiletype.attrs
local floor_shape = df.tiletype_shape.FLOOR
local wall_shape = df.tiletype_shape.WALL
local frozen_liquid_material = df.tiletype_material.FROZEN_LIQUID
local no_dig = df.tile_dig_designation.No

local target_tiles = 0
local target_dig_designations = 0
local target_floor_tiles = 0
local target_frozen_liquid_tiles = 0
local target_wall_tiles = 0
local target_hidden_tiles = 0
local target_visible_tiles = 0
local target_missing_blocks = 0

local function get_tile_block(tx, ty, tz)
  if tx < 0 or ty < 0 or tz < 0 then
    return nil
  end
  return dfhack.maps.getTileBlock(tx, ty, tz)
end

local function scan_rect(ax1, ay1, az, ax2, ay2)
  local rect = {
    tiles = 0,
    dig_designations = 0,
    floor_tiles = 0,
    frozen_liquid_tiles = 0,
    wall_tiles = 0,
    hidden_tiles = 0,
    visible_tiles = 0,
    missing_blocks = 0,
  }

  for tx = ax1, ax2 do
    for ty = ay1, ay2 do
      rect.tiles = rect.tiles + 1
      local block = get_tile_block(tx, ty, az)
      if block then
        local dx = tx % 16
        local dy = ty % 16
        local designation = block.designation[dx][dy]
        if designation and designation.dig ~= no_dig then
          rect.dig_designations = rect.dig_designations + 1
        end
        if designation and designation.hidden then
          rect.hidden_tiles = rect.hidden_tiles + 1
        elseif designation then
          rect.visible_tiles = rect.visible_tiles + 1
        end

        local tiletype = block.tiletype[dx][dy]
        local attr = attrs[tiletype]
        if attr then
          if attr.material == frozen_liquid_material then
            rect.frozen_liquid_tiles = rect.frozen_liquid_tiles + 1
          elseif attr.shape == floor_shape then
            rect.floor_tiles = rect.floor_tiles + 1
          elseif attr.shape == wall_shape then
            rect.wall_tiles = rect.wall_tiles + 1
          end
        end
      else
        rect.missing_blocks = rect.missing_blocks + 1
      end
    end
  end

  return rect
end

if not global_only then
  for tx = rx1, rx2 do
    for ty = ry1, ry2 do
      target_tiles = target_tiles + 1
      local block = get_tile_block(tx, ty, rz)
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
          if attr.material == frozen_liquid_material then
            target_frozen_liquid_tiles = target_frozen_liquid_tiles + 1
          elseif attr.shape == floor_shape then
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
end

local plan_ry2 = math.max(ry2, ry1 + 4)
local connector_x1 = rx2 + 1
local connector_y1 = ry1 + 2
local connector_x2 = rx2 + 3
local connector_y2 = connector_y1
local workshop_room_x1 = rx2 + 4
local workshop_room_y1 = ry1
local workshop_room_x2 = rx2 + 8
local workshop_room_y2 = plan_ry2
local function empty_rect()
  return {
    tiles = 0,
    dig_designations = 0,
    floor_tiles = 0,
    frozen_liquid_tiles = 0,
    wall_tiles = 0,
    hidden_tiles = 0,
    visible_tiles = 0,
    missing_blocks = 0,
  }
end

local fortress_connector = empty_rect()
local fortress_workshop_room = empty_rect()
if not global_only then
  fortress_connector = scan_rect(
    connector_x1, connector_y1, rz, connector_x2, connector_y2
  )
  fortress_workshop_room = scan_rect(
    workshop_room_x1,
    workshop_room_y1,
    rz,
    workshop_room_x2,
    workshop_room_y2
  )
end

local function is_completed_space(rect)
  return rect.tiles > 0
      and rect.missing_blocks == 0
      and rect.floor_tiles >= rect.tiles
      and rect.wall_tiles == 0
      and rect.hidden_tiles == 0
end

local fortress_complexity_spaces_completed = 0
if not global_only and is_completed_space(fortress_connector) then
  fortress_complexity_spaces_completed = fortress_complexity_spaces_completed + 1
end
if not global_only and is_completed_space(fortress_workshop_room) then
  fortress_complexity_spaces_completed = fortress_complexity_spaces_completed + 1
end

local active_jobs = 0
local active_dig_jobs = 0
local active_construct_building_jobs = 0
local active_carpenter_jobs = 0
local active_job_type_names = {}

local function append_limited(list, value, limit)
  if not value or value == '' then return end
  if #list >= limit then return end
  table.insert(list, value)
end

local function job_type_name(job)
  local ok, name = pcall(function()
    return tostring(df.job_type[job.job_type] or job.job_type)
  end)
  if ok and name then return name end
  return ''
end

if df.global.world.jobs and df.global.world.jobs.list then
  local link = df.global.world.jobs.list.next
  while link do
    local job = link.item
    active_jobs = active_jobs + 1
    local name = job_type_name(job)
    if job.job_type == df.job_type.Dig
        or name == 'DigChannel'
        or name == 'CarveUpwardStaircase'
        or name == 'CarveDownwardStaircase'
        or name == 'CarveUpDownStaircase' then
      active_dig_jobs = active_dig_jobs + 1
    end
    append_limited(active_job_type_names, name, 12)
    if job.job_type == df.job_type.ConstructBuilding or name == 'ConstructBuilding' then
      active_construct_building_jobs = active_construct_building_jobs + 1
    end
    if string.find(name:lower(), 'carpenter', 1, true)
        or string.find(name:lower(), 'wood', 1, true)
        or name == 'ConstructBed'
        or name == 'ConstructDoor'
        or name == 'ConstructTable'
        or name == 'ConstructChair' then
      active_carpenter_jobs = active_carpenter_jobs + 1
    end
    link = link.next
  end
end

local manager_orders_count = 0
local manager_orders_amount_left = 0
local manager_orders_amount_total = 0
if df.global.world.manager_orders then
  for _, order in ipairs(df.global.world.manager_orders) do
    manager_orders_count = manager_orders_count + 1
    manager_orders_amount_left = manager_orders_amount_left + (tonumber(order.amount_left) or 0)
    manager_orders_amount_total = manager_orders_amount_total + (tonumber(order.amount_total) or 0)
  end
end

local workshop_count = 0
local carpenter_workshops = 0
local carpenter_workshops_usable = 0
local carpenter_workshop_task_jobs = 0
local carpenter_workshop_construction_jobs = 0
local carpenter_workshop_task_job_type_names = {}
local carpenter_workshop_construction_job_type_names = {}
local carpenter_workshop_x1 = nil
local carpenter_workshop_y1 = nil
local carpenter_workshop_x2 = nil
local carpenter_workshop_y2 = nil
local carpenter_workshop_z = nil
local buildings = df.global.world.buildings and df.global.world.buildings.all
if buildings then
  pcall(function()
    local carpenter_type = nil
    if df.workshop_type then
      carpenter_type = df.workshop_type.Carpenters or df.workshop_type.Carpenter
    end
    for _, building in ipairs(buildings) do
      local is_workshop = false
      local ok_type, building_type = pcall(function() return building:getType() end)
      if ok_type and building_type == df.building_type.Workshop then
        is_workshop = true
      end
      local ok_instance, is_instance = pcall(function()
        return df.building_workshopst and df.building_workshopst:is_instance(building)
      end)
      if ok_instance and is_instance then
        is_workshop = true
      end

      if is_workshop then
        workshop_count = workshop_count + 1
        local ok_workshop_type, workshop_type = pcall(function() return building.type end)
        local workshop_type_name = ok_workshop_type and tostring(workshop_type) or ''
        if (ok_workshop_type and carpenter_type and workshop_type == carpenter_type)
            or workshop_type_name == 'Carpenters'
            or workshop_type_name == 'Carpenter' then
          carpenter_workshops = carpenter_workshops + 1
          local building_complete = false
          pcall(function()
            building_complete = building:getBuildStage() >= building:getMaxBuildStage()
          end)
          if building_complete then
            carpenter_workshops_usable = carpenter_workshops_usable + 1
          end
          if carpenter_workshop_x1 == nil then
            pcall(function()
              carpenter_workshop_x1 = building.x1
              carpenter_workshop_y1 = building.y1
              carpenter_workshop_x2 = building.x2
              carpenter_workshop_y2 = building.y2
              carpenter_workshop_z = building.z
            end)
          end
          local building_task_jobs = 0
          local building_construction_jobs = 0
          local ok_jobs = pcall(function()
            if building.jobs then
              for _, job in ipairs(building.jobs) do
                local name = job_type_name(job)
                if job.job_type == df.job_type.ConstructBuilding or name == 'ConstructBuilding' then
                  building_construction_jobs = building_construction_jobs + 1
                  append_limited(carpenter_workshop_construction_job_type_names, name, 12)
                else
                  building_task_jobs = building_task_jobs + 1
                  append_limited(carpenter_workshop_task_job_type_names, name, 12)
                end
              end
            end
          end)
          if ok_jobs then
            carpenter_workshop_task_jobs = carpenter_workshop_task_jobs + building_task_jobs
            carpenter_workshop_construction_jobs = carpenter_workshop_construction_jobs + building_construction_jobs
          end
        end
      end
    end
  end)
end

local citizens_total = 0
local miners_total = 0
local carpenter_labors_enabled = 0
local citizens_on_target_z = 0
local labor_state_complete = true
if df.global.world.units and df.global.world.units.active then
  for _, unit in ipairs(df.global.world.units.active) do
    local ok_citizen, is_citizen = pcall(function()
      return dfhack.units.isCitizen(unit)
    end)
    if not ok_citizen then
      labor_state_complete = false
    elseif is_citizen and not dfhack.units.isDead(unit) then
      citizens_total = citizens_total + 1
      if not global_only and unit.pos and unit.pos.z == rz then
        citizens_on_target_z = citizens_on_target_z + 1
      end
      local ok_adult, is_adult = pcall(function()
        return dfhack.units.isAdult(unit)
      end)
      if not ok_adult or type(is_adult) ~= 'boolean' then
        labor_state_complete = false
      elseif is_adult then
        local is_miner = false
        local is_carpenter = false
        local ok_labors = pcall(function()
          if not unit.status or not unit.status.labors then
            error('labor_state_unavailable')
          end
          for labor, enabled in pairs(unit.status.labors) do
            if enabled then
              local labor_name = tostring(labor)
              if labor_name == 'MINE' then
                is_miner = true
              elseif labor_name == 'CARPENTER' then
                is_carpenter = true
              end
            end
          end
        end)
        if ok_labors then
          if is_miner then miners_total = miners_total + 1 end
          if is_carpenter then carpenter_labors_enabled = carpenter_labors_enabled + 1 end
        else
          labor_state_complete = false
        end
      end
    end
  end
end

local out = {
  ok = true,
  observation_scope = global_only and 'global' or 'target',
  active_jobs = active_jobs,
  active_dig_jobs = active_dig_jobs,
  active_construct_building_jobs = active_construct_building_jobs,
  active_carpenter_jobs = active_carpenter_jobs,
  active_job_type_names = active_job_type_names,
  manager_orders_count = manager_orders_count,
  manager_orders_amount_left = manager_orders_amount_left,
  manager_orders_amount_total = manager_orders_amount_total,
  workshop_count = workshop_count,
  carpenter_workshops = carpenter_workshops,
  carpenter_workshops_planned = carpenter_workshops,
  carpenter_workshops_usable = carpenter_workshops_usable,
  carpenter_workshops_unproven = math.max(0, carpenter_workshops - carpenter_workshops_usable),
  carpenter_workshop_task_jobs = carpenter_workshop_task_jobs,
  carpenter_workshop_construction_jobs = carpenter_workshop_construction_jobs,
  carpenter_workshop_task_job_type_names = carpenter_workshop_task_job_type_names,
  carpenter_workshop_construction_job_type_names = carpenter_workshop_construction_job_type_names,
  carpenter_workshop_x1 = carpenter_workshop_x1,
  carpenter_workshop_y1 = carpenter_workshop_y1,
  carpenter_workshop_x2 = carpenter_workshop_x2,
  carpenter_workshop_y2 = carpenter_workshop_y2,
  carpenter_workshop_z = carpenter_workshop_z,
  citizens_total = citizens_total,
  miners_total = miners_total,
  carpenter_labors_enabled = carpenter_labors_enabled,
  labor_state_complete = labor_state_complete,
  citizens_on_target_z = citizens_on_target_z,
}

if not global_only then
  out.target_rect = { rx1, ry1, rz, rx2, ry2, rz }
  out.target_z = rz
  out.window_x = window_x
  out.window_y = window_y
  out.window_z = window_z
  out.cursor_x = cursor_x
  out.cursor_y = cursor_y
  out.cursor_z = cursor_z
  out.target_tiles = target_tiles
  out.target_dig_designations = target_dig_designations
  out.target_floor_tiles = target_floor_tiles
  out.target_frozen_liquid_tiles = target_frozen_liquid_tiles
  out.target_wall_tiles = target_wall_tiles
  out.target_hidden_tiles = target_hidden_tiles
  out.target_visible_tiles = target_visible_tiles
  out.target_missing_blocks = target_missing_blocks
  out.fortress_plan_name = 'two_room_workshop'
  out.fortress_connector_rect = {
    connector_x1, connector_y1, rz, connector_x2, connector_y2, rz,
  }
  out.fortress_workshop_room_rect = {
    workshop_room_x1, workshop_room_y1, rz, workshop_room_x2, workshop_room_y2, rz,
  }
  out.fortress_connector_tiles = fortress_connector.tiles
  out.fortress_connector_floor_tiles = fortress_connector.floor_tiles
  out.fortress_connector_frozen_liquid_tiles = fortress_connector.frozen_liquid_tiles
  out.fortress_connector_wall_tiles = fortress_connector.wall_tiles
  out.fortress_connector_hidden_tiles = fortress_connector.hidden_tiles
  out.fortress_connector_missing_blocks = fortress_connector.missing_blocks
  out.fortress_workshop_room_tiles = fortress_workshop_room.tiles
  out.fortress_workshop_room_floor_tiles = fortress_workshop_room.floor_tiles
  out.fortress_workshop_room_frozen_liquid_tiles = fortress_workshop_room.frozen_liquid_tiles
  out.fortress_workshop_room_wall_tiles = fortress_workshop_room.wall_tiles
  out.fortress_workshop_room_hidden_tiles = fortress_workshop_room.hidden_tiles
  out.fortress_workshop_room_missing_blocks = fortress_workshop_room.missing_blocks
  out.fortress_complexity_tiles = fortress_connector.tiles + fortress_workshop_room.tiles
  out.fortress_complexity_floor_tiles =
    fortress_connector.floor_tiles + fortress_workshop_room.floor_tiles
  out.fortress_complexity_frozen_liquid_tiles =
    fortress_connector.frozen_liquid_tiles + fortress_workshop_room.frozen_liquid_tiles
  out.fortress_complexity_wall_tiles =
    fortress_connector.wall_tiles + fortress_workshop_room.wall_tiles
  out.fortress_complexity_hidden_tiles =
    fortress_connector.hidden_tiles + fortress_workshop_room.hidden_tiles
  out.fortress_complexity_missing_blocks =
    fortress_connector.missing_blocks + fortress_workshop_room.missing_blocks
  out.fortress_complexity_spaces_completed = fortress_complexity_spaces_completed
end

print(json.encode(out))
