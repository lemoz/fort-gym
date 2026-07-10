-- job_metrics.lua: read-only crew/job/workshop observability for governed runs.
-- Reports citizen labor counts, active jobs by type, every workshop with its
-- construction stage, and (optionally) the tile composition of a bounded rect.
-- Never mutates game state.

local json = require('json')
local args = {...}

local MAX_JOB_ENTRIES = 12
local MAX_TRACKED_JOB_IDS = 256
local MAX_WORKSHOPS = 10
local MAX_WORKSHOP_JOB_ENTRIES = 12
local MAX_CITIZEN_ENTRIES = 20
local MAX_RECT_W, MAX_RECT_H = 30, 30

local ORDER_JOB_ITEMS = {
  ConstructBed = 'bed',
  ConstructDoor = 'door',
  ConstructTable = 'table',
  ConstructThrone = 'chair',
  MakeBarrel = 'barrel',
  ConstructBin = 'bin',
}

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

local function raw_flag(flags, name)
  local ok, value = pcall(function() return flags[name] and true or false end)
  return ok and value or false
end

local function strict_raw_flag(flags, name)
  local ok, value = pcall(function() return flags[name] and true or false end)
  if not ok then error('plant_flag_unreadable:' .. tostring(name)) end
  return value
end

local function usable_seed(item)
  local flags = item and item.flags
  if not flags then return false, false end
  local rejected = false
  local readable = pcall(function()
    rejected = flags.dump
      or flags.forbid
      or flags.garbage_collect
      or flags.hostile
      or flags.on_fire
      or flags.rotten
      or flags.trader
      or flags.in_building
      or flags.construction
      or flags.artifact
  end)
  return readable and not rejected, readable
end

local seed_counts_by_index = {}
local seed_scan_ok = pcall(function()
  for _, item in ipairs(df.global.world.items.other.SEEDS or {}) do
    local usable, readable = usable_seed(item)
    if not readable then error('seed_flags_unreadable') end
    if usable then
      seed_counts_by_index[item.mat_index] =
        (seed_counts_by_index[item.mat_index] or 0) + (tonumber(item.stack_size) or 1)
    end
  end
end)
if not seed_scan_ok then seed_counts_by_index = {} end

local SEASON_FLAG = { 'SPRING', 'SUMMER', 'AUTUMN', 'WINTER' }

local function underground_offers()
  local offers = { {}, {}, {}, {} }
  local truncated = { false, false, false, false }
  local scan_ok = pcall(function()
    for index, plant in ipairs(_plant_raws) do
      local flags = plant.flags
      local surface_crop = plant.underground_depth_min == 0
        or plant.underground_depth_max == 0
      if (seed_counts_by_index[index] or 0) > 0
          and strict_raw_flag(flags, 'SEED')
          and not strict_raw_flag(flags, 'TREE')
          and not surface_crop
          and strict_raw_flag(flags, 'BIOME_SUBTERRANEAN_WATER') then
        for season = 1, 4 do
          if strict_raw_flag(flags, SEASON_FLAG[season]) then
            if #offers[season] < 12 then
              table.insert(offers[season], sanitize(plant.id))
            else
              truncated[season] = true
            end
          end
        end
      end
    end
    for season = 1, 4 do table.sort(offers[season]) end
  end)
  local offered = {
    spring = offers[1],
    summer = offers[2],
    autumn = offers[3],
    winter = offers[4],
  }
  local truncation = {
    spring = truncated[1],
    summer = truncated[2],
    autumn = truncated[3],
    winter = truncated[4],
  }
  return offered, truncation, scan_ok
end

local offered_crops_by_season, crop_options_truncated, crop_option_scan_ok =
  underground_offers()
local crop_options_any_truncated = crop_options_truncated.spring
  or crop_options_truncated.summer
  or crop_options_truncated.autumn
  or crop_options_truncated.winter

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
    construct_building_walk_group_connected = 0,
    construct_building_walk_group_disconnected = 0,
    construct_building_walk_group_unknown = 0,
    workshop_task = 0,
    plant_seeds = 0,
    brew_reaction = 0,
    suspended = 0,
    entries = {},
    active_ids = {},
    active_ids_truncated = false,
    order_jobs = {},
    order_jobs_truncated = false,
  },
  workshops = {},
}

-- citizens and labors
local citizen_units = {}

local function unit_position(unit)
  local ok, x, y, z = pcall(function() return dfhack.units.getPosition(unit) end)
  if not ok or x == nil or y == nil or z == nil or x < 0 or y < 0 or z < 0 then
    return nil
  end
  return { x = x, y = y, z = z }
end

local function item_position(item)
  local ok, x, y, z = pcall(function() return dfhack.items.getPosition(item) end)
  if not ok or x == nil or y == nil or z == nil or x < 0 or y < 0 or z < 0 then
    return nil
  end
  return { x = x, y = y, z = z }
end

for _, unit in ipairs(df.global.world.units.active) do
  local ok, is_citizen = pcall(function() return dfhack.units.isCitizen(unit) end)
  if ok and is_citizen then
    local path_pos = unit_position(unit)
    local ok_available, available = pcall(function()
      return not dfhack.units.isDead(unit) and not (unit.flags1 and unit.flags1.caged)
    end)
    if ok_available and available and path_pos then
      table.insert(citizen_units, { unit = unit, pos = path_pos })
    end
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
        pos = path_pos and { path_pos.x, path_pos.y, path_pos.z } or false,
        labors = citizen_enabled_labors(unit),
        current_job_type = current_job_type,
      })
    end
  end
end

local function construction_job_connectivity(job)
  local items = {}
  for _, item_ref in ipairs(job.items) do
    if item_ref.item then
      local pos = item_position(item_ref.item)
      if not pos then return 'unknown', {} end
      table.insert(items, { item = item_ref.item, pos = pos })
    end
  end
  if #items == 0 or df.global.world.reindex_pathfinding then return 'unknown', items end

  local checked = false
  local unknown_seen = false
  for _, citizen in ipairs(citizen_units) do
    local ok_target, target_connected = pcall(function()
      return dfhack.maps.canWalkBetween(citizen.pos, job.pos)
    end)
    if not ok_target then
      unknown_seen = true
    else
      checked = true
      if target_connected then
        local all_items_connected = true
        for _, entry in ipairs(items) do
          local ok_item, item_connected = pcall(function()
            return dfhack.maps.canWalkBetween(citizen.pos, entry.pos)
          end)
          if not ok_item then
            unknown_seen = true
            all_items_connected = false
            break
          end
          if not item_connected then
            all_items_connected = false
            break
          end
        end
        if all_items_connected then return 'connected', items end
      end
    end
  end
  if unknown_seen then return 'unknown', items end
  return checked and 'disconnected' or 'unknown', items
end

-- world job list
local link = df.global.world.jobs.list.next
while link do
  local job = link.item
  if job then
    out.jobs.total = out.jobs.total + 1
    if #out.jobs.active_ids < MAX_TRACKED_JOB_IDS then
      table.insert(out.jobs.active_ids, job.id)
    end
    local name = job_type_name(job.job_type)
    if name == 'Dig'
        or name == 'DigChannel'
        or name == 'CarveUpwardStaircase'
        or name == 'CarveDownwardStaircase'
        or name == 'CarveUpDownStaircase' then
      out.jobs.dig = out.jobs.dig + 1
    elseif name == 'ConstructBuilding' then
      out.jobs.construct_building = out.jobs.construct_building + 1
    end
    if name == 'PlantSeeds' then out.jobs.plant_seeds = out.jobs.plant_seeds + 1 end
    local reaction_name = false
    pcall(function()
      if job.reaction_name and job.reaction_name ~= '' then
        reaction_name = sanitize(job.reaction_name)
      end
    end)
    if reaction_name == 'BREW_DRINK_FROM_PLANT' then
      out.jobs.brew_reaction = out.jobs.brew_reaction + 1
    end
    local order_item = ORDER_JOB_ITEMS[name]
    if reaction_name == 'BREW_DRINK_FROM_PLANT' then order_item = 'brew' end
    if order_item then
      if #out.jobs.order_jobs < MAX_TRACKED_JOB_IDS then
        table.insert(out.jobs.order_jobs, { id = job.id, item = order_item })
      else
        out.jobs.order_jobs_truncated = true
      end
    end
    local walk_group_connectivity, assigned_items = nil, nil
    if name == 'ConstructBuilding' then
      walk_group_connectivity, assigned_items = construction_job_connectivity(job)
      local count_key = 'construct_building_walk_group_' .. walk_group_connectivity
      out.jobs[count_key] = out.jobs[count_key] + 1
    end
    local suspended = job.flags.suspend and true or false
    if suspended then out.jobs.suspended = out.jobs.suspended + 1 end
    if #out.jobs.entries < MAX_JOB_ENTRIES then
      local entry = {
        id = job.id,
        type = name,
        reaction = reaction_name,
        pos = { job.pos.x, job.pos.y, job.pos.z },
        suspended = suspended,
        has_worker = job_has_worker(job),
      }
      if name == 'ConstructBuilding' then
        entry.walk_group_connectivity = walk_group_connectivity
        entry.assigned_items = {}
        for _, assigned in ipairs(assigned_items or {}) do
          table.insert(entry.assigned_items, {
            id = assigned.item.id,
            pos = { assigned.pos.x, assigned.pos.y, assigned.pos.z },
          })
        end
        local first = assigned_items and assigned_items[1] or nil
        if first then
          entry.assigned_item_id = first.item.id
          entry.assigned_item_pos = {
            first.pos.x,
            first.pos.y,
            first.pos.z,
          }
        end
      end
      table.insert(out.jobs.entries, entry)
    end
  end
  link = link.next
end
out.jobs.active_ids_truncated = out.jobs.total > #out.jobs.active_ids

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

-- Raw production inputs. These are inventory facts, not a prediction that a
-- queued job will succeed: the simulation still decides item assignment.
out.production_inputs = {
  brewable_plant_stacks = 0,
  brewable_plant_units = 0,
  brewable_plant_stacks_in_jobs = 0,
  empty_barrels = 0,
  empty_barrels_in_jobs = 0,
  total_barrels = 0,
}
do
  for _, item in ipairs(df.global.world.items.other.IN_PLAY) do
    local ok_type, item_type = pcall(function() return df.item_type[item:getType()] end)
    if ok_type and item_type == 'PLANT' then
      local ok_brewable, brewable = pcall(function()
        local mat = dfhack.matinfo.decode(item)
        return mat and mat.material and mat.material.flags.ALCOHOL_PLANT and true or false
      end)
      if ok_brewable and brewable then
        local in_job = item.flags and item.flags.in_job and true or false
        if in_job then
          out.production_inputs.brewable_plant_stacks_in_jobs =
            out.production_inputs.brewable_plant_stacks_in_jobs + 1
        else
          out.production_inputs.brewable_plant_stacks =
            out.production_inputs.brewable_plant_stacks + 1
          local stack_size = 1
          pcall(function() stack_size = math.max(1, tonumber(item.stack_size) or 1) end)
          out.production_inputs.brewable_plant_units =
            out.production_inputs.brewable_plant_units + stack_size
        end
      end
    elseif ok_type and item_type == 'BARREL' then
      out.production_inputs.total_barrels = out.production_inputs.total_barrels + 1
      local ok_contents, contents = pcall(function()
        return dfhack.items.getContainedItems(item)
      end)
      if ok_contents and contents and #contents == 0 then
        if item.flags and item.flags.in_job then
          out.production_inputs.empty_barrels_in_jobs =
            out.production_inputs.empty_barrels_in_jobs + 1
        else
          out.production_inputs.empty_barrels = out.production_inputs.empty_barrels + 1
        end
      end
    end
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

local function building_stage(bld)
  local ok, stage, max_stage = pcall(function()
    return bld:getBuildStage(), bld:getMaxBuildStage()
  end)
  stage = ok and tonumber(stage) or nil
  max_stage = ok and tonumber(max_stage) or nil
  local stage_read_ok = ok and stage ~= nil and max_stage ~= nil and max_stage > 0
  if not stage_read_ok then return false, 0, 0, false end
  return true, stage, max_stage, stage >= max_stage
end

local function building_is_complete(bld)
  local _, _, _, built = building_stage(bld)
  return built
end

-- farm plots placed (G7 survival primitive: see build_farm_plot.lua)
out.farm_plots = 0
out.farm_plot_positions = {}
-- per-plot crop selection detail (id, rect, stage, seasonal crop tokens).
-- Each crops entry is a 4-slot array [spring,summer,autumn,winter]; an empty
-- slot is emitted as false so the array stays dense (json-safe).
out.farm_plot_details = {}

local function farm_plot_detail(bld)
  local stage_read_ok, stage, max_stage, built = building_stage(bld)
  local crops = { false, false, false, false }
  pcall(function()
    for s = 0, 3 do
      crops[s + 1] = plant_token(bld.plant_id[s]) or false
    end
  end)
  local tile_context = {
    total = 0,
    readable = 0,
    outside = 0,
    light = 0,
    subterranean = 0,
    water_table = 0,
  }
  for x = bld.x1, bld.x2 do
    for y = bld.y1, bld.y2 do
      tile_context.total = tile_context.total + 1
      pcall(function()
        local block = dfhack.maps.getTileBlock(x, y, bld.z)
        if not block then return end
        local designation = block.designation[x % 16][y % 16]
        if not designation or designation.hidden then return end
        tile_context.readable = tile_context.readable + 1
        if designation.outside then tile_context.outside = tile_context.outside + 1 end
        if designation.light then tile_context.light = tile_context.light + 1 end
        if designation.subterranean then
          tile_context.subterranean = tile_context.subterranean + 1
        end
        if designation.water_table then
          tile_context.water_table = tile_context.water_table + 1
        end
      end)
    end
  end
  local plot_subterranean = tile_context.total > 0
    and tile_context.readable == tile_context.total
    and tile_context.subterranean == tile_context.total
  local crop_options_complete = built
    and plot_subterranean
    and seed_scan_ok
    and crop_option_scan_ok
    and not crop_options_any_truncated
  return {
    id = bld.id,
    rect = { bld.x1, bld.y1, bld.x2, bld.y2, bld.z },
    stage = stage,
    max_stage = max_stage,
    stage_read_ok = stage_read_ok,
    built = built,
    crops = crops,
    tile_context = tile_context,
    plot_subterranean = plot_subterranean,
    crop_options_complete = crop_options_complete,
    crop_options_seed_scan_ok = seed_scan_ok,
    crop_options_scan_ok = crop_option_scan_ok,
    crop_options_truncated = crop_options_truncated,
    crop_options_scope = crop_options_complete
      and 'native_seed_season_depth_subterranean_water'
      or 'unsupported_or_incomplete',
    offered_crops_by_season = crop_options_complete and offered_crops_by_season or {
      spring = {}, summer = {}, autumn = {}, winter = {},
    },
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
    local stage_read_ok, stage, max_stage, built = building_stage(bld)
    local queued = 0
    pcall(function() queued = #bld.jobs end)
    local queued_job_details = {}
    pcall(function()
      for _, job in ipairs(bld.jobs) do
        if #queued_job_details >= MAX_WORKSHOP_JOB_ENTRIES then break end
        local reaction = false
        if job.reaction_name and job.reaction_name ~= '' then
          reaction = sanitize(job.reaction_name)
        end
        table.insert(queued_job_details, {
          id = job.id,
          type = job_type_name(job.job_type),
          reaction = reaction,
          suspended = job.flags.suspend and true or false,
          has_worker = job_has_worker(job),
        })
      end
    end)
    out.jobs.workshop_task = out.jobs.workshop_task + queued
    table.insert(out.workshops, {
      id = bld.id,
      subtype = tostring(subtype),
      pos = { bld.centerx, bld.centery, bld.z },
      built = built,
      stage_read_ok = stage_read_ok,
      stage = stage,
      max_stage = max_stage,
      queued_jobs = queued,
      queued_job_details = queued_job_details,
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
  local cause_source = false
  local ok_cause, cause_value = pcall(function() return unit.counters.death_cause end)
  local cause_number = ok_cause and tonumber(cause_value) or nil
  if cause_number then cause_enum = cause_number end
  if cause_number and cause_number >= 0 then
    local ok_name, name = pcall(function() return df.death_type[cause_number] end)
    if ok_name and name and tostring(name) ~= 'NONE' then
      cause_name = sanitize(name)
      cause_known = true
      cause_source = 'counters.death_cause'
    end
  end

  return {
    unit_id = unit_id,
    cause_enum = cause_enum,
    cause_name = cause_name,
    cause_known = cause_known,
    cause_source = cause_source,
    incident_id = dead_value(unit, 'counters', 'death_id'),
    hunger_timer = dead_value(unit, 'counters2', 'hunger_timer'),
    thirst_timer = dead_value(unit, 'counters2', 'thirst_timer'),
    stored_fat = dead_value(unit, 'counters2', 'stored_fat'),
    stomach_food = dead_value(unit, 'counters2', 'stomach_food'),
    -- A current-condition flag, not authoritative historical cause evidence.
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
    local counts = {
      wall = 0,
      tree = 0,
      floor = 0,
      frozen_liquid = 0,
      shrub = 0,
      shrub_or_other = 0,
      designated = 0,
    }
    local shapes = df.tiletype.attrs
    for x = rx1, rx2 do
      for y = ry1, ry2 do
        local block = dfhack.maps.getTileBlock(x, y, rz)
        if block then
          local dx, dy = x % 16, y % 16
          local ok, shape, is_tree, is_frozen_liquid = pcall(function()
            local attr = shapes[block.tiletype[dx][dy]]
            return df.tiletype_shape[attr.shape],
              attr.material == df.tiletype_material.TREE,
              attr.material == df.tiletype_material.FROZEN_LIQUID
          end)
          local shape_name = ok and tostring(shape) or '?'
          if ok and is_frozen_liquid then
            counts.frozen_liquid = counts.frozen_liquid + 1
          elseif shape_name == 'WALL' and ok and is_tree then
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
      frozen_liquid = counts.frozen_liquid,
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
  local seed_indices = {}
  for index in pairs(seed_counts_by_index) do table.insert(seed_indices, index) end
  table.sort(seed_indices)
  for _, index in ipairs(seed_indices) do
    if #out.seeds >= 12 then break end
    local count = seed_counts_by_index[index]
    local tok = plant_token(index)
    if tok then
      local subterranean = false
      local seasons = {}
      pcall(function()
        local pf = _plant_raws[index].flags
        subterranean = pf.BIOME_SUBTERRANEAN_WATER and true or false
        if pf.SPRING then table.insert(seasons, 'sp') end
        if pf.SUMMER then table.insert(seasons, 'su') end
        if pf.AUTUMN then table.insert(seasons, 'au') end
        if pf.WINTER then table.insert(seasons, 'wi') end
      end)
      table.insert(out.seeds, {
        token = tok,
        count = count,
        surface = not subterranean,
        seasons = seasons,
      })
    end
  end
end

print(json.encode(out))
