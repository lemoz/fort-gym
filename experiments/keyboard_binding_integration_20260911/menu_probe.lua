-- Operator positioning is limited to disposable copies; inspect is read-only.
local json=require('json')
local mode=({...})[1]
assert(mode=='inspect' or mode=='reset' or mode=='select')
local out={}
dfhack.with_suspend(function()
  assert(dfhack.isMapLoaded() and dfhack.world.isFortressMode())
  assert(df.global.pause_state==true)
  assert(df.global.cur_year==30 and df.global.cur_year_tick==152201)
  local target
  for _,b in ipairs(df.global.world.buildings.all) do
    if b:getType()==df.building_type.Workshop
        and df.workshop_type[b:getSubtype()]=='Carpenters'
        and b:getBuildStage()>=b:getMaxBuildStage() then
      if not target or b.id<target.id then target=b end
    end
  end
  assert(target,'No completed carpenter workshop')
  local pos={x=target.centerx,y=target.centery,z=target.z}
  if mode=='reset' then
    dfhack.gui.resetDwarfmodeView(true)
    dfhack.gui.revealInDwarfmodeMap(pos,true)
  elseif mode=='select' then
    df.global.cursor:assign(pos)
    dfhack.gui.revealInDwarfmodeMap(pos,true)
    dfhack.gui.refreshSidebar()
  end
  local view=dfhack.gui.getCurViewscreen(true)
  local selected=dfhack.gui.getSelectedBuilding(true)
  local has_name,name=pcall(function() return target.name end)
  out={schema_version='fortgym.private-binding-integration-scan/v1',
    mode=mode,dfhack_version=dfhack.getDFHackVersion(),
    year=df.global.cur_year,year_tick=df.global.cur_year_tick,paused=df.global.pause_state,
    focus=dfhack.gui.getFocusString(view),
    cursor={x=df.global.cursor.x,y=df.global.cursor.y,z=df.global.cursor.z},
    target={id=target.id,position=pos,subtype=df.workshop_type[target:getSubtype()],
      name_available=has_name and type(name)=='string',
      name=has_name and type(name)=='string' and name or json.null},
    selected_building_id=selected and selected.id or -1,jobs={}}
  for _,job in ipairs(target.jobs) do
    table.insert(out.jobs,{id=job.id,type=df.job_type[job.job_type],
      reaction_name=job.reaction_name or '',suspend=job.flags.suspend,
      repeat_job=job.flags['repeat']})
  end
end)
print(json.encode(out))
