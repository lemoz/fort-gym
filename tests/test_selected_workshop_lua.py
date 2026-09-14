"""Execute the shipped Lua with native-engine doubles, not gameplay evidence."""

import shutil
import subprocess
from pathlib import Path

import pytest

LUA = shutil.which("lua")
SOURCE = (Path(__file__).resolve().parents[1] / "hook/campaign_selected_workshop_job_v1.lua").read_text()
PRELUDE = r"""
local captured, locked, allocations, linked, refreshes = nil, false, 0, {}, 0
local loaded, removed, complete, selected, fail_at = true, false, true, true, nil
local function vector()
  return setmetatable({}, {__index={insert=function(self,index,value)
    assert(index=='#'); table.insert(self,value)
  end}})
end
local building={id=7, x1=20, y1=30, z=4, jobs=vector(), subtype=1}
function building:getType() return 9 end
function building:getSubtype() return self.subtype end
function building:getCustomType() return -1 end
function building:getBuildStage() return complete and 3 or 0 end
function building:getMaxBuildStage() return 3 end
local view={native=true}
local defs={
  {job_fields={job_type=1}, items={{item_type=55,flags1={wood=true}}}},
  {job_fields={job_type=7,reaction_name='BREW_DRINK_FROM_PLANT'},
   items={{item_type=77,reagent_index=0}}},
}
df={
  global={cur_year=30, cur_year_tick=123, pause_state=true, job_next_id=100,
    world={cur_savegame={save_dir='fixture'}},ui={main={mode=8}}},
  ui_sidebar_mode={QueryBuilding=8},
  viewscreen_dwarfmodest={is_instance=function(self,v) return v and v.native end},
  building_workshopst={is_instance=function(self,b) return b==building end},
  workshop_type={Carpenters=1,Still=2},job_type={ConstructBed=1,CustomReaction=7},
  job={new=function()
    assert(locked); allocations=allocations+1
    if fail_at==allocations then error('injected allocation failure') end
    local job={flags={},pos={},job_items=vector(),general_refs=vector()}
    function job:assign(fields) for k,v in pairs(fields) do self[k]=v end end
    return job
  end},
  general_ref_building_holderst={},
}
dfhack={
  getDFPath=function() return '/isolated' end,
  isMapLoaded=function() return loaded end,
  world={isFortressMode=function() return loaded end},
  with_suspend=function(fn)
    assert(not locked); locked=true
    local ok,err=pcall(fn); locked=false
    if not ok then error(err) end
  end,
  gui={
    getCurViewscreen=function(skip) assert(locked and skip); return view end,
    getSelectedBuilding=function(silent) assert(locked and silent); return selected and building or nil end,
    refreshSidebar=function() assert(locked); refreshes=refreshes+1 end,
  },
  buildings={markedForRemoval=function(b) assert(b==building); return removed end},
  job={linkIntoWorld=function(job,new_id)
    assert(locked and new_id)
    job.id=df.global.job_next_id; df.global.job_next_id=df.global.job_next_id+1
    table.insert(linked,job)
    return true
  end},
}
require=function(name)
  if name=='json' then return {encode=function(value) captured=value; return '{}' end} end
  if name=='utils' then return {clone=function(value,deep)
    assert(deep); local out={}; for k,v in pairs(value) do out[k]=v end; return out
  end} end
  assert(name=='dfhack.workshops')
  return {getJobs=function(bt,st,ct)
    assert(locked and bt==9 and st==building.subtype and ct==-1); return defs
  end}
end
print=function(value) assert(value=='{}') end
"""


def run(setup="", args="'/isolated','30','123','fixture','bed','2'", assertions=""):
    if LUA is None:
        pytest.skip("Lua interpreter unavailable")
    script = PRELUDE + setup + "\nlocal function hook(...)\n" + SOURCE
    script += "\nend\nhook(" + args + ")\nassert(not locked)\n" + assertions
    result = subprocess.run([LUA, "-"], input=script, text=True, capture_output=True, timeout=5)
    assert result.returncode == 0, result.stderr


def test_only_selected_workshop_gets_normal_jobs_and_real_material_filters():
    run(assertions="""
assert(captured.ok and captured.jobs_queued==2 and #building.jobs==2)
assert(captured.command_mutation=='completed' and refreshes==1)
assert(captured.queue_before==0 and captured.queue_after==2)
assert(#linked==2 and linked[1].id==100 and linked[2].id==101)
assert(df.global.job_next_id==102 and df.global.cur_year_tick==123 and df.global.pause_state)
for _,job in ipairs(linked) do
  assert(job.job_type==1 and job.flags.special and job.completion_timer==-1)
  assert(job.job_items[1].item_type==55 and job.job_items[1].flags1.wood)
  assert(job.general_refs[1].building_id==7 and job.pos.z==4)
end
assert(defs[1].items[1].new==nil)
""")


def test_brew_is_native_plant_reaction_at_the_selected_still():
    run("building.subtype=2", "'/isolated','30','123','fixture','brew','1'", """
assert(captured.ok and captured.jobs_queued==1)
assert(linked[1].job_type==7 and linked[1].reaction_name=='BREW_DRINK_FROM_PLANT')
assert(linked[1].job_items[1].item_type==77 and linked[1].job_items[1].reagent_index==0)
""")


@pytest.mark.parametrize("setup,error", [
    ("selected=false", "selected_workshop_unavailable"),
    ("removed=true", "selected_workshop_unavailable"),
    ("complete=false", "selected_workshop_unavailable"),
    ("building.subtype=2", "selected_workshop_wrong_type"),
    ("df.global.ui.main.mode=0", "select_workshop_in_query_menu"),
    ("view.native=false", "select_workshop_in_query_menu"),
    ("defs={}", "unsupported_selected_workshop_job"),
    ("loaded=false", "fortress_not_loaded"),
    ("df.global.pause_state=false", "boundary_mismatch"),
    ("df.global.cur_year_tick=124", "boundary_mismatch"),
    ("df.global.world.cur_savegame.save_dir='other'", "boundary_mismatch"),
    ("for i=1,9 do building.jobs:insert('#',{}) end", "selected_workshop_queue_full"),
])
def test_no_fallback_workshop_or_partial_batch_on_preflight_rejection(setup, error):
    run(setup, assertions=f"""
assert(not captured.ok and captured.error=='{error}')
assert(captured.command_mutation=='not_attempted' and captured.jobs_queued==0)
assert(allocations==0 and #linked==0 and refreshes==0 and df.global.job_next_id==100)
""")


@pytest.mark.parametrize("item,quantity", [("unknown", "1"), ("bed", "0"), ("bed", "6"), ("bed", "1.5")])
def test_invalid_quantity_is_rejected_not_clamped(item, quantity):
    run(args=f"'/isolated','30','123','fixture','{item}','{quantity}'", assertions="""
assert(not captured.ok and captured.error=='invalid_request')
assert(captured.command_mutation=='not_attempted' and allocations==0)
""")


def test_partial_allocation_failure_is_not_reported_as_no_mutation():
    run("fail_at=2", assertions="""
assert(not captured.ok and captured.command_mutation=='attempted')
assert(captured.jobs_queued==1 and #linked==1 and #building.jobs==1)
assert(df.global.job_next_id==101 and refreshes==0)
""")
