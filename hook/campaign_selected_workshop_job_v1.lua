-- Explicit production-job shorthand at the workshop selected by the player.
-- Unlike the historical order_make helper, never searches world buildings.
local json = require('json')
local utils = require('utils')
local workshops = require('dfhack.workshops')
local args = {...}
local root, year, tick, save = args[1], tonumber(args[2]), tonumber(args[3]), args[4]
local item, quantity = args[5], tonumber(args[6])
local result = {schema_version='fortgym.selected-workshop-job/v1', ok=false,
  command_mutation='not_attempted', jobs_queued=0, created_job_ids={}}
local specs = {
  bed={'ConstructBed','Carpenters'}, door={'ConstructDoor','Carpenters'},
  table={'ConstructTable','Carpenters'}, chair={'ConstructThrone','Carpenters'},
  barrel={'MakeBarrel','Carpenters'}, bin={'ConstructBin','Carpenters'},
  brew={'CustomReaction','Still','BREW_DRINK_FROM_PLANT'},
}
local function integer(value)
  return type(value)=='number' and value==math.floor(value)
    and value~=math.huge and value~=-math.huge
end
if #args~=6 or type(root)~='string' or root=='' or not integer(year) or year<0
    or not integer(tick) or tick<0 or tick>=403200 or type(save)~='string' or save==''
    or not specs[item] or not integer(quantity) or quantity<1 or quantity>5 then
  result.error='invalid_request'; print(json.encode(result)); return
end
result.item, result.quantity = item, quantity
local function boundary()
  return {dfroot=dfhack.getDFPath(), year=df.global.cur_year,
    year_tick=df.global.cur_year_tick, paused=df.global.pause_state,
    save_name=df.global.world.cur_savegame.save_dir}
end
local function matches(point)
  return point.dfroot==root and point.year==year and point.year_tick==tick
    and point.save_name==save and point.paused==true
end
local locked, failure = pcall(dfhack.with_suspend, function()
  if not dfhack.isMapLoaded() or not dfhack.world.isFortressMode() then
    result.error='fortress_not_loaded'; return
  end
  result.before=boundary()
  if not matches(result.before) then result.error='boundary_mismatch'; return end
  local view=dfhack.gui.getCurViewscreen(true)
  if not df.viewscreen_dwarfmodest:is_instance(view)
      or df.global.ui.main.mode~=df.ui_sidebar_mode.QueryBuilding then
    result.error='select_workshop_in_query_menu'; return
  end
  local building=dfhack.gui.getSelectedBuilding(true)
  if not df.building_workshopst:is_instance(building)
      or dfhack.buildings.markedForRemoval(building)
      or building:getBuildStage()<building:getMaxBuildStage() then
    result.error='selected_workshop_unavailable'; return
  end
  local spec=specs[item]
  if building:getSubtype()~=df.workshop_type[spec[2]] then
    result.error='selected_workshop_wrong_type'; return
  end
  if #building.jobs+quantity>10 then result.error='selected_workshop_queue_full'; return end
  local entry=nil
  for _, candidate in pairs(workshops.getJobs(
      building:getType(), building:getSubtype(), building:getCustomType()) or {}) do
    if candidate.job_fields and candidate.job_fields.job_type==df.job_type[spec[1]]
        and (not spec[3] or candidate.job_fields.reaction_name==spec[3]) then
      entry=candidate; break
    end
  end
  if not entry then result.error='unsupported_selected_workshop_job'; return end
  result.workshop_id=building.id
  result.queue_before=#building.jobs
  -- A failed/partial mutation is retained, never silently retried or rolled back.
  result.command_mutation='attempted'
  for _=1,quantity do
    local job=df.job:new()
    job.flags.special=true
    job.completion_timer=-1
    job.pos.x, job.pos.y, job.pos.z=building.x1, building.y1, building.z
    job:assign(entry.job_fields)
    for _, filter in ipairs(entry.items or {}) do
      local copy=utils.clone(filter, true)
      copy.new=true
      job.job_items:insert('#', copy)
    end
    job.general_refs:insert('#', {new=df.general_ref_building_holderst, building_id=building.id})
    building.jobs:insert('#', job)
    -- linkIntoWorld assigns the id; do not also increment job_next_id here.
    if dfhack.job.linkIntoWorld(job, true)~=true then
      error('native_job_link_failed')
    end
    table.insert(result.created_job_ids, job.id)
    result.jobs_queued=result.jobs_queued+1
  end
  result.queue_after=#building.jobs
  dfhack.gui.refreshSidebar()
  result.after=boundary()
  if not matches(result.after) then result.error='boundary_changed'; return end
  if result.queue_after~=result.queue_before+quantity then
    result.error='queue_count_mismatch'; return
  end
  result.command_mutation='completed'
  result.ok=true
end)
if not locked then result.error=tostring(failure); result.ok=false end
print(json.encode(result))
