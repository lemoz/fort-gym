-- job_metrics.lua: read-only crew/job/workshop observability for governed runs.
-- Reports citizen labor counts, active jobs by type, every workshop with its
-- construction stage, and (optionally) the tile composition of a bounded rect.
-- Never mutates game state.

local json = require('json')
local args = {...}

local MAX_JOB_ENTRIES = 12
local MAX_WORKSHOPS = 10
local MAX_CITIZEN_ENTRIES = 20
local MAX_RECT_W, MAX_RECT_H = 30, 30

-- Friendly labor name -> df.unit_labor enum name. Mirrors LABOR_WHITELIST in
-- hook/set_labor.lua and dfhack_backend.py so the per-citizen observation lists
-- exactly the labors the LABOR action can flip. Each enum is pcall-guarded so a
-- name absent on this DF build is simply skipped, never a crash.
local LABOR_WHITELIST = {
  { name = 'mine', enum = 'MINE' },
  { name = 'woodcutting', enum = 'CUTWOOD' },
  { name = 'carpentry', enum = 'CARPENTER' },
  { name = 'masonry', enum = 'MASON' },
  { name = 'farming', enum = 'PLANT' },
  { name = 'herbalism', enum = 'HERBALIST' },
  { name = 'brewing', enum = 'BREWER' },
  { name = 'fishing', enum = 'FISH' },
  { name = 'construction', enum = 'BUILD_CONSTRUCTION' },
  { name = 'cooking', enum = 'COOK' },
}

local function to_int(v)
  local n = tonumber(v)
  if not n then return nil end
  return math.floor(n)
end

local function sanitize(text)
  local ok, cleaned = pcall(function()
    return tostring(text):gsub('[^%w %p]', '?')
  end)
  if ok then return cleaned end
  return '?'
end

local SEASON_NAMES = { 'spring', 'summer', 'autumn', 'winter' }

-- Resolve a plant raw index to its token (df.global.world.raws.plants.all[i].id).
-- Returns nil for an empty slot (-1) or an unreadable index.
local _plant_raws = df.global.world.raws.plants.all
local function plant_token(idx)
  if idx == nil or idx < 0 then return nil end
  local ok, tok = pcall(function() return _plant_raws[idx].id end)
  if ok and tok and tok ~= '' then return sanitize(tok) end
  return nil
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

-- Enabled whitelist labors (friendly names) for one citizen.
local function citizen_enabled_labors(unit)
  local names = {}
  for _, entry in ipairs(LABOR_WHITELIST) do
    if labor_enabled(unit, entry.enum) then
      table.insert(names, entry.name)
    end
  end
  return names
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
    -- per-citizen detail (cap MAX_CITIZEN_ENTRIES): id, enabled whitelist
    -- labors, and current job type. The LABOR action targets a unit by id, so
    -- the agent needs the id -> labors mapping to choose whom to reassign.
    list = {},
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
    if #out.citizens.list < MAX_CITIZEN_ENTRIES then
      local current_job_type = nil
      if has_job then
        pcall(function()
          current_job_type = sanitize(df.job_type[unit.job.current_job.job_type])
        end)
      end
      table.insert(out.citizens.list, {
        id = unit.id,
        labors = citizen_enabled_labors(unit),
        current_job_type = current_job_type,
      })
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
local GOODS_ITEM_TYPES = { 'BED', 'DOOR', 'TABLE', 'CHAIR', 'BARREL', 'BIN', 'WOOD', 'DRINK' }
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
-- Keep placed_furniture's existing "present or being installed" meaning, but
-- expose a separate count for furniture whose construction stage is complete.
out.placed_furniture_completed = { bed = 0, door = 0, table = 0, chair = 0 }
out.placed_furniture_positions = { bed = {}, door = {}, table = {}, chair = {} }

local function building_is_complete(bld)
  local ok, complete = pcall(function()
    return bld:getBuildStage() >= bld:getMaxBuildStage()
  end)
  return ok and complete or false
end

-- farm plots placed (G7 survival primitive: see build_farm_plot.lua)
out.farm_plots = 0
out.farm_plot_positions = {}
-- per-plot crop selection detail (id, rect, stage, seasonal crop tokens).
-- Each crops entry is a 4-slot array [spring,summer,autumn,winter]; an empty
-- slot is emitted as false so the array stays dense (json-safe).
out.farm_plot_details = {}

local function farm_plot_detail(bld)
  local stage, max_stage = 0, 0
  pcall(function()
    stage = bld:getBuildStage()
    max_stage = bld:getMaxBuildStage()
  end)
  local crops = { false, false, false, false }
  pcall(function()
    for s = 0, 3 do
      crops[s + 1] = plant_token(bld.plant_id[s]) or false
    end
  end)
  return {
    id = bld.id,
    rect = { bld.x1, bld.y1, bld.x2, bld.y2, bld.z },
    stage = stage,
    max_stage = max_stage,
    built = stage >= max_stage,
    crops = crops,
  }
end

-- workshops with construction stage and queued jobs
for _, bld in ipairs(df.global.world.buildings.all) do
  local ok_type, bld_type = pcall(function() return bld:getType() end)
  if ok_type and FURNITURE_BUILDING_KEYS[bld_type] then
    local key = FURNITURE_BUILDING_KEYS[bld_type]
    out.placed_furniture[key] = out.placed_furniture[key] + 1
    if building_is_complete(bld) then
      out.placed_furniture_completed[key] = out.placed_furniture_completed[key] + 1
    end
    if #out.placed_furniture_positions[key] < 8 then
      pcall(function()
        table.insert(
          out.placed_furniture_positions[key],
          { bld.centerx, bld.centery, bld.z }
        )
      end)
    end
  end
  if ok_type and bld_type == df.building_type.FarmPlot then
    out.farm_plots = out.farm_plots + 1
    if #out.farm_plot_positions < 8 then
      pcall(function()
        table.insert(out.farm_plot_positions, { bld.centerx, bld.centery, bld.z })
      end)
    end
    if #out.farm_plot_details < 8 then
      pcall(function()
        table.insert(out.farm_plot_details, farm_plot_detail(bld))
      end)
    end
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

-- Dead citizens remain in world.units.all after death. Read only the raw
-- DF 0.47.05 fields here; each lookup is pcall-guarded for adjacent layouts.
-- No cause is inferred from hunger, thirst, or stress counters.
out.dead_citizen_count = 0
out.dead_citizen_records = {}
local all_causes_known = true

local function dead_value(unit, field_table, field)
  local ok, value = pcall(function()
    local values = unit[field_table]
    return values and values[field] or nil
  end)
  if ok and value ~= nil then return value end
  return false
end

local function dead_flag(unit, field_table, field)
  local ok, value = pcall(function()
    local flags = unit[field_table]
    return flags and flags[field] and true or false
  end)
  return ok and value or false
end

local function dead_citizen_record(unit)
  local ok_id, unit_id = pcall(function() return unit.id end)
  if not ok_id or unit_id == nil then return nil, false end

  local cause_enum, cause_name, cause_known = false, false, false
  local ok_cause, cause_value = pcall(function() return unit.counters.death_cause end)
  local cause_number = ok_cause and tonumber(cause_value) or nil
  if cause_number and cause_number >= 0 then
    cause_enum = cause_number
    local ok_name, name = pcall(function() return df.death_type[cause_number] end)
    if ok_name and name and tostring(name) ~= 'NONE' then
      cause_name = sanitize(name)
      cause_known = true
    end
  end

  return {
    unit_id = unit_id,
    cause_enum = cause_enum,
    cause_name = cause_name,
    cause_known = cause_known,
    incident_id = dead_value(unit, 'counters', 'death_id'),
    hunger_timer = dead_value(unit, 'counters2', 'hunger_timer'),
    thirst_timer = dead_value(unit, 'counters2', 'thirst_timer'),
    stored_fat = dead_value(unit, 'counters2', 'stored_fat'),
    stomach_food = dead_value(unit, 'counters2', 'stomach_food'),
    drowning = dead_flag(unit, 'flags1', 'drowning'),
    suffocation = dead_value(unit, 'counters', 'suffocation'),
    emotionally_overloaded = dead_flag(unit, 'flags3', 'emotionally_overloaded'),
  }, cause_known
end

local dead_scan_ok = pcall(function()
  local civ_id = df.global.ui.civ_id
  for _, unit in ipairs(df.global.world.units.all) do
    local ok_dead, is_dead_citizen = pcall(function()
      return unit.civ_id == civ_id
        and dfhack.units.isDwarf(unit)
        and dfhack.units.isDead(unit)
    end)
    if ok_dead and is_dead_citizen then
      out.dead_citizen_count = out.dead_citizen_count + 1
      local record, cause_known = dead_citizen_record(unit)
      if record then
        table.insert(out.dead_citizen_records, record)
        if not cause_known then all_causes_known = false end
      else
        all_causes_known = false
      end
    end
  end
end)

-- A failed record must fail closed: unknown evidence is not a known-safe cause.
out.death_evidence_complete = dead_scan_ok
  and #out.dead_citizen_records == out.dead_citizen_count
out.death_causes_known = out.death_evidence_complete and all_causes_known

-- optional bounded rect tile composition
local x1, y1, z1 = to_int(args[1]), to_int(args[2]), to_int(args[3])
local x2, y2, z2 = to_int(args[4]), to_int(args[5]), to_int(args[6])
if x1 and y1 and z1 and x2 and y2 and z2 and z1 == z2 then
  local rx1, ry1, rz = math.min(x1, x2), math.min(y1, y2), z1
  local rx2, ry2 = math.max(x1, x2), math.max(y1, y2)
  if (rx2 - rx1 + 1) <= MAX_RECT_W and (ry2 - ry1 + 1) <= MAX_RECT_H then
    local counts = { wall = 0, tree = 0, floor = 0, shrub = 0, shrub_or_other = 0, designated = 0 }
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
          elseif shape_name == 'SHRUB' then
            counts.shrub = counts.shrub + 1
            counts.shrub_or_other = counts.shrub_or_other + 1
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
      shrub = counts.shrub,
      shrub_or_other = counts.shrub_or_other,
      designated = counts.designated,
    }
  end
end

-- Seeds on hand summarised per plant token (informational planting evidence):
-- token -> {count, surface bool, seasons abbrevs}. Capped at 12 tokens.
out.seeds = {}
out.current_season = SEASON_NAMES[(df.global.cur_season or 0) + 1] or 'unknown'
do
  local summary = {}
  local order = {}
  pcall(function()
    local seeds = df.global.world.items.other.SEEDS
    if not seeds then return end
    for _, item in ipairs(seeds) do
      local mi = item.mat_index
      local tok = plant_token(mi)
      if tok then
        local entry = summary[tok]
        if not entry and #order < 12 then
          local subterranean = false
          local seasons = {}
          pcall(function()
            local pf = _plant_raws[mi].flags
            subterranean = pf.BIOME_SUBTERRANEAN_WATER and true or false
            if pf.SPRING then table.insert(seasons, 'sp') end
            if pf.SUMMER then table.insert(seasons, 'su') end
            if pf.AUTUMN then table.insert(seasons, 'au') end
            if pf.WINTER then table.insert(seasons, 'wi') end
          end)
          entry = { count = 0, surface = not subterranean, seasons = seasons }
          summary[tok] = entry
          table.insert(order, tok)
        end
        if entry then entry.count = entry.count + 1 end
      end
    end
  end)
  for _, tok in ipairs(order) do
    local e = summary[tok]
    table.insert(out.seeds, {
      token = tok,
      count = e.count,
      surface = e.surface,
      seasons = e.seasons,
    })
  end
end

print(json.encode(out))
