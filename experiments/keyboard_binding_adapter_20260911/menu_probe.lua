-- Operator-only UI setup and read-only queue inspection on disposable copies.
local json=require('json')
local args={...}
local mode=args[1]
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
  assert(target,'No completed carpenter workshop in the source save')
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
  local selected_job=dfhack.gui.getSelectedWorkshopJob(true)
  out={
    schema_version='fortgym.private-keyboard-menu-scan/v1',
    dfhack_version=dfhack.getDFHackVersion(), mode=mode,
    year=df.global.cur_year,year_tick=df.global.cur_year_tick,paused=df.global.pause_state,
    focus=dfhack.gui.getFocusString(view),
    target={id=target.id,subtype=df.workshop_type[target:getSubtype()],position=pos},
    selected_building_id=selected and selected.id or -1,
    selected_job_id=selected_job and selected_job.id or -1,
    jobs={},key_values={},
  }
  for _,job in ipairs(target.jobs) do
    table.insert(out.jobs,{id=job.id,type=df.job_type[job.job_type],
        reaction_name=job.reaction_name or '',suspend=job.flags.suspend,
        repeat_job=job.flags['repeat']})
  end
  for _,key in ipairs({'CUSTOM_B','STRING_A098','HOTKEY_CARPENTER_BED',
      'STANDARDSCROLL_DOWN','SELECT','D_BUILDJOB','BUILDJOB_ADD'}) do
    out.key_values[key]=df.interface_key[key]
  end
end)
print(json.encode(out))
