-- order_make.lua: enqueue a safe manager order.

local json = require('json')
local utils = require('utils')
local workshop_jobs = require('dfhack.workshops')
local args = {...}
local item = tostring(args[1] or '')
local qty = tonumber(args[2]) or 1

local whitelist = {
  bed = 'ConstructBed',
  door = 'ConstructDoor',
  table = 'ConstructTable',
  chair = 'ConstructThrone',
  barrel = 'MakeBarrel',
  bin = 'ConstructBin',
}

local jobname = whitelist[item]
if not jobname then
  print(json.encode({ ok = false, error = 'invalid_item' }))
  return
end

if qty < 1 or qty > 5 then qty = 1 end

local job_type = df.job_type[jobname]
if not job_type then
  print(json.encode({ ok = false, error = 'unsupported_job_type', job = jobname }))
  return
end

local function record_manager_order(job_type, qty)
  local manager_orders = df.global.world.manager_orders
  if not manager_orders then
    return false
  end
  local wo = df.manager_order:new()
  wo.job_type = job_type
  wo.amount_total = qty
  wo.amount_left = qty
  manager_orders:insert('#', wo)
  return true
end

local function is_carpenter_workshop(building)
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

  local carpenter_type = nil
  if df.workshop_type then
    carpenter_type = df.workshop_type.Carpenters or df.workshop_type.Carpenter
  end
  local ok_workshop_type, workshop_type = pcall(function() return building.type end)
  local workshop_type_name = ok_workshop_type and tostring(workshop_type) or ''
  return (ok_workshop_type and carpenter_type and workshop_type == carpenter_type)
      or workshop_type_name == 'Carpenters'
      or workshop_type_name == 'Carpenter'
end

local function first_carpenter_workshop()
  local buildings = df.global.world.buildings and df.global.world.buildings.all
  if not buildings then return nil end
  for _, building in ipairs(buildings) do
    if is_carpenter_workshop(building) then
      return building
    end
  end
  return nil
end

local function job_definition_for(building, wanted_job_type)
  local defs = workshop_jobs.getJobs(
    building:getType(),
    building:getSubtype(),
    building:getCustomType()
  )
  if not defs then return nil end
  for _, entry in pairs(defs) do
    if entry.job_fields and entry.job_fields.job_type == wanted_job_type then
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

local workshop = first_carpenter_workshop()
if workshop then
  local entry = job_definition_for(workshop, job_type)
  if entry then
    local created_jobs = {}
    for _ = 1, qty do
      local job = create_workshop_job(workshop, entry)
      table.insert(created_jobs, job.id)
    end
    local manager_recorded = record_manager_order(job_type, qty)
    print(json.encode({
      ok = true,
      item = item,
      qty = qty,
      mode = 'workshop_job',
      workshop_id = workshop.id,
      created_job_ids = created_jobs,
      manager_recorded = manager_recorded,
    }))
    return
  end
end

if not record_manager_order(job_type, qty) then
  print(json.encode({ ok = false, error = 'manager_orders_unavailable' }))
  return
end

local processed_ok, processed_error = pcall(function()
  dfhack.run_script('orders', 'process-new')
end)

print(json.encode({
  ok = true,
  item = item,
  qty = qty,
  processed = processed_ok,
  process_error = processed_ok and nil or tostring(processed_error),
}))
