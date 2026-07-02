-- job_metrics.lua: read-only crew/job/workshop observability for governed runs.
-- Reports citizen labor counts, active jobs by type, every workshop with its
-- construction stage, and (optionally) the tile composition of a bounded rect.
-- Never mutates game state.

local json = require('json')
local args = {...}

local MAX_JOB_ENTRIES = 12
local MAX_WORKSHOPS = 10
local MAX_RECT_W, MAX_RECT_H = 30, 30

local function to_int(v)
  local n = tonumber(v)
  if not n then return nil end
  return math.floor(n)
end

local function labor_enabled(unit, labor_name)
  local ok, enabled = pcall(function()
    local labor = df.unit_labor[labor_name]
    if labor == nil then return false end
    return unit.status.labors[labor] and true or false
  end)
  if not ok then return false end
  return enabled and true or false
end

local function job_type_name(job_type)
  local ok, name = pcall(function() return df.job_type[job_type] end)
  if ok and name then return tostring(name) end
  return tostring(job_type)
end

local function job_has_worker(job)
  for _, ref in ipairs(job.general_refs) do
    local ok, is_worker = pcall(function()
      return df.general_ref_unit_workerst:is_instance(ref)
    end)
    if ok and is_worker then return true end
  end
  return false
end

local out = {
  ok = true,
  citizens = {
    total = 0,
    idle = 0,
    mining_labor = 0,
    carpentry_labor = 0,
    woodcutting_labor = 0,
    masonry_labor = 0,
    herbalism_labor = 0,
  },
  jobs = {
    total = 0,
    dig = 0,
    construct_building = 0,
    workshop_task = 0,
    suspended = 0,
    entries = {},
  },
  workshops = {},
}

-- citizens and labors
for _, unit in ipairs(df.global.world.units.active) do
  local ok, is_citizen = pcall(function() return dfhack.units.isCitizen(unit) end)
  if ok and is_citizen then
    out.citizens.total = out.citizens.total + 1
    local has_job = unit.job and unit.job.current_job and true or false
    if not has_job then out.citizens.idle = out.citizens.idle + 1 end
    if labor_enabled(unit, 'MINE') then
      out.citizens.mining_labor = out.citizens.mining_labor + 1
    end
    if labor_enabled(unit, 'CARPENTER') then
      out.citizens.carpentry_labor = out.citizens.carpentry_labor + 1
    end
    if labor_enabled(unit, 'CUTWOOD') then
      out.citizens.woodcutting_labor = out.citizens.woodcutting_labor + 1
    end
    if labor_enabled(unit, 'MASON') then
      out.citizens.masonry_labor = out.citizens.masonry_labor + 1
    end
    if labor_enabled(unit, 'HERBALIST') then
      out.citizens.herbalism_labor = out.citizens.herbalism_labor + 1
    end
  end
end

-- world job list
local link = df.global.world.jobs.list.next
while link do
  local job = link.item
  if job then
    out.jobs.total = out.jobs.total + 1
    local name = job_type_name(job.job_type)
    if name == 'Dig' or name == 'DigChannel' then
      out.jobs.dig = out.jobs.dig + 1
    elseif name == 'ConstructBuilding' then
      out.jobs.construct_building = out.jobs.construct_building + 1
    end
    local suspended = job.flags.suspend and true or false
    if suspended then out.jobs.suspended = out.jobs.suspended + 1 end
    if #out.jobs.entries < MAX_JOB_ENTRIES then
      table.insert(out.jobs.entries, {
        type = name,
        pos = { job.pos.x, job.pos.y, job.pos.z },
        suspended = suspended,
        has_worker = job_has_worker(job),
      })
    end
  end
  link = link.next
end

-- finished goods and logs currently in play (read-only counts)
local GOODS_ITEM_TYPES = { 'BED', 'DOOR', 'TABLE', 'CHAIR', 'BARREL', 'BIN', 'WOOD' }
do
  local counts = {}
  for _, item in ipairs(df.global.world.items.other.IN_PLAY) do
    local ok, name = pcall(function() return df.item_type[item:getType()] end)
    if ok and name then
      counts[name] = (counts[name] or 0) + 1
    end
  end
  out.goods = {}
  for _, key in ipairs(GOODS_ITEM_TYPES) do
    out.goods[string.lower(key)] = counts[key] or 0
  end
end

-- placed furniture buildings (installed or being installed)
local FURNITURE_BUILDING_KEYS = {
  [df.building_type.Bed] = 'bed',
  [df.building_type.Door] = 'door',
  [df.building_type.Table] = 'table',
  [df.building_type.Chair] = 'chair',
}
out.placed_furniture = { bed = 0, door = 0, table = 0, chair = 0 }

-- workshops with construction stage and queued jobs
for _, bld in ipairs(df.global.world.buildings.all) do
  local ok_type, bld_type = pcall(function() return bld:getType() end)
  if ok_type and FURNITURE_BUILDING_KEYS[bld_type] then
    local key = FURNITURE_BUILDING_KEYS[bld_type]
    out.placed_furniture[key] = out.placed_furniture[key] + 1
  end
  local ok, is_workshop = pcall(function()
    return bld:getType() == df.building_type.Workshop
  end)
  if ok and is_workshop and #out.workshops < MAX_WORKSHOPS then
    local subtype = ''
    pcall(function()
      subtype = df.workshop_type[bld:getSubtype()] or tostring(bld:getSubtype())
    end)
    local stage, max_stage = 0, 0
    pcall(function()
      stage = bld:getBuildStage()
      max_stage = bld:getMaxBuildStage()
    end)
    local queued = 0
    pcall(function() queued = #bld.jobs end)
    out.jobs.workshop_task = out.jobs.workshop_task + queued
    table.insert(out.workshops, {
      id = bld.id,
      subtype = tostring(subtype),
      pos = { bld.centerx, bld.centery, bld.z },
      built = stage >= max_stage,
      stage = stage,
      max_stage = max_stage,
      queued_jobs = queued,
    })
  end
end

-- optional bounded rect tile composition
local x1, y1, z1 = to_int(args[1]), to_int(args[2]), to_int(args[3])
local x2, y2, z2 = to_int(args[4]), to_int(args[5]), to_int(args[6])
if x1 and y1 and z1 and x2 and y2 and z2 and z1 == z2 then
  local rx1, ry1, rz = math.min(x1, x2), math.min(y1, y2), z1
  local rx2, ry2 = math.max(x1, x2), math.max(y1, y2)
  if (rx2 - rx1 + 1) <= MAX_RECT_W and (ry2 - ry1 + 1) <= MAX_RECT_H then
    local counts = { wall = 0, tree = 0, floor = 0, shrub_or_other = 0, designated = 0 }
    local shapes = df.tiletype.attrs
    for x = rx1, rx2 do
      for y = ry1, ry2 do
        local block = dfhack.maps.getTileBlock(x, y, rz)
        if block then
          local dx, dy = x % 16, y % 16
          local ok, shape, is_tree = pcall(function()
            local attr = shapes[block.tiletype[dx][dy]]
            return df.tiletype_shape[attr.shape],
              attr.material == df.tiletype_material.TREE
          end)
          local shape_name = ok and tostring(shape) or '?'
          if shape_name == 'WALL' and ok and is_tree then
            counts.tree = counts.tree + 1
          elseif shape_name == 'WALL' then
            counts.wall = counts.wall + 1
          elseif shape_name == 'FLOOR' then
            counts.floor = counts.floor + 1
          else
            counts.shrub_or_other = counts.shrub_or_other + 1
          end
          local des_ok, designated = pcall(function()
            return block.designation[dx][dy].dig ~= df.tile_dig_designation.No
          end)
          if des_ok and designated then
            counts.designated = counts.designated + 1
          end
        end
      end
    end
    out.rect_tiles = {
      rect = { rx1, ry1, rz, rx2, ry2, rz },
      wall = counts.wall,
      tree = counts.tree,
      floor = counts.floor,
      shrub_or_other = counts.shrub_or_other,
      designated = counts.designated,
    }
  end
end

print(json.encode(out))
