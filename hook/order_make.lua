-- order_make.lua: enqueue a safe manager order.

local json = require('json')
local utils = require('utils')
local workshop_jobs = require('dfhack.workshops')
local args = {...}
local item = tostring(args[1] or '')
local qty = tonumber(args[2]) or 1

-- Each item maps to a DF job type AND the workshop subtype that job runs at
-- (a player queues bed/door/table/chair/barrel/bin at a Carpenter's
-- Workshop). Brewing is NOT a discrete job type on 0.47.05 -- live
-- validation 2026-07-08 showed df.job_type.BrewDrink does not exist; a
-- Still's job list offers CustomReaction entries, and brewing is the
-- BREW_DRINK_FROM_PLANT reaction. Reaction-backed items carry `reaction`
-- and are matched on job_fields.reaction_name below.
local ITEM_JOBS = {
  bed = { job = 'ConstructBed', workshop = 'Carpenters' },
  door = { job = 'ConstructDoor', workshop = 'Carpenters' },
  table = { job = 'ConstructTable', workshop = 'Carpenters' },
  chair = { job = 'ConstructThrone', workshop = 'Carpenters' },
  barrel = { job = 'MakeBarrel', workshop = 'Carpenters' },
  bin = { job = 'ConstructBin', workshop = 'Carpenters' },
  brew = { job = 'CustomReaction', reaction = 'BREW_DRINK_FROM_PLANT', workshop = 'Still' },
}

local spec = ITEM_JOBS[item]
if not spec then
  print(json.encode({ ok = false, error = 'invalid_item' }))
  return
end
local jobname = spec.job

if qty < 1 or qty > 5 then qty = 1 end

local job_type = df.job_type[jobname]
if not job_type then
  print(json.encode({ ok = false, error = 'unsupported_job_type', job = jobname }))
  return
end

-- subtype_name is the DF workshop_type name string (e.g. "Carpenters",
-- "Still") -- the same convention used for the Carpenters/Carpenter naming
-- quirk this already defended against.
local function is_workshop_of_subtype(building, subtype_name)
  if not building then return false end
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
  if not is_workshop then return false end

  local ok_removal, marked_for_removal = pcall(function()
    return dfhack.buildings.markedForRemoval(building)
  end)
  if not ok_removal or marked_for_removal then return false end

  local ok_stage, is_complete = pcall(function()
    return building:getBuildStage() >= building:getMaxBuildStage()
  end)
  if not ok_stage or not is_complete then return false end

  local target_type = df.workshop_type and df.workshop_type[subtype_name] or nil
  local ok_workshop_type, workshop_type = pcall(function() return building.type end)
  local workshop_type_name = ok_workshop_type and tostring(workshop_type) or ''
  return (ok_workshop_type and target_type ~= nil and workshop_type == target_type)
      or workshop_type_name == subtype_name
      -- Carpenters/Carpenter naming quirk, preserved for the carpenter path
      or (subtype_name == 'Carpenters' and workshop_type_name == 'Carpenter')
end

local function first_workshop_of_subtype(subtype_name)
  local buildings = df.global.world.buildings and df.global.world.buildings.all
  if not buildings then return nil end
  for _, building in ipairs(buildings) do
    if is_workshop_of_subtype(building, subtype_name) then
      return building
    end
  end
  return nil
end

local function job_definition_for(building, wanted_job_type, wanted_reaction)
  local defs = workshop_jobs.getJobs(
    building:getType(),
    building:getSubtype(),
    building:getCustomType()
  )
  if not defs then return nil end
  for _, entry in pairs(defs) do
    if entry.job_fields and entry.job_fields.job_type == wanted_job_type
        and (not wanted_reaction
             or entry.job_fields.reaction_name == wanted_reaction) then
      return entry
    end
  end
  return nil
end

local function create_workshop_job(building, entry)
  local job = df.job:new()
  job.id = df.global.job_next_id
  df.global.job_next_id = df.global.job_next_id + 1
  job.flags.special = true
  job.completion_timer = -1
  job.pos.x = building.x1
  job.pos.y = building.y1
  job.pos.z = building.z
  if entry.job_fields then
    job:assign(entry.job_fields)
  end
  for _, filter in ipairs(entry.items or {}) do
    local job_item = utils.clone(filter, true)
    job_item.new = true
    job.job_items:insert('#', job_item)
  end
  job.general_refs:insert('#', {
    new = df.general_ref_building_holderst,
    building_id = building.id,
  })
  building.jobs:insert('#', job)
  dfhack.job.linkIntoWorld(job, true)
  return job
end

local workshop = first_workshop_of_subtype(spec.workshop)
if not workshop then
  print(json.encode({
    ok = false,
    error = 'required_workshop_unavailable',
    item = item,
    required_workshop = spec.workshop,
  }))
  return
end

local entry = job_definition_for(workshop, job_type, spec.reaction)
if not entry then
  print(json.encode({
    ok = false,
    error = 'unsupported_workshop_job',
    item = item,
    required_workshop = spec.workshop,
    workshop_id = workshop.id,
  }))
  return
end

local created_jobs = {}
for _ = 1, qty do
  local job = create_workshop_job(workshop, entry)
  table.insert(created_jobs, job.id)
end

print(json.encode({
  ok = true,
  item = item,
  qty = qty,
  mode = 'workshop_job',
  workshop_id = workshop.id,
  created_job_ids = created_jobs,
  -- Direct workshop jobs are the requested quantity. Do not also insert a
  -- manager order, which could enqueue the same quantity a second time.
  manager_recorded = false,
}))
