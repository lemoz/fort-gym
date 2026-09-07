"""Exercise shipped Lua input code with engine doubles, not a live fortress."""

import shutil
import subprocess
from pathlib import Path

import pytest

LUA = shutil.which("lua")
SOURCE = (Path(__file__).resolve().parents[1] / "hook/campaign_keyboard_v1.lua").read_text()
PRELUDE = r"""
local captured, suspended, inputs, input_failure = nil, false, 0, false
local loaded, change_clock, change_save = true, false, false
local current = {_type='viewscreen_dwarfmodest',focus='dwarfmode/Default'}
df = {
  global={cur_year=30,cur_year_tick=123,pause_state=true,
    world={cur_savegame={save_dir='fixture'}}},
  interface_key={CURSOR_UP=1,D_PAUSE=2,SELECT=3,LEAVESCREEN=4},
}
dfhack = {
  getDFPath=function() return '/isolated' end,
  isMapLoaded=function() return loaded end,
  world={isFortressMode=function() return loaded end},
  with_suspend=function(fn)
    assert(not suspended); suspended=true
    local ok,err=pcall(fn)
    suspended=false
    if not ok then error(err) end
  end,
  gui={
    getCurViewscreen=function(skip) assert(suspended and skip); return current end,
    getFocusString=function(view) return view.focus end,
  },
}
require = function(name)
  if name=='json' then
    return {encode=function(value) captured=value; return '{}' end}
  end
  assert(name=='gui')
  return {simulateInput=function(view,key)
    assert(suspended and view==current)
    inputs=inputs+1
    if key==2 then df.global.pause_state=false end
    if key==3 then current={_type='viewscreen_storesst',focus='stocks'} end
    if change_clock then df.global.cur_year_tick=124 end
    if change_save then df.global.world.cur_savegame.save_dir='other' end
    if input_failure then error('injected input failure') end
  end}
end
print = function(value) assert(value=='{}') end
"""


def run(setup, arguments, assertions):
    if LUA is None:
        pytest.skip("Lua interpreter unavailable")
    source = (
        PRELUDE
        + setup
        + "\nlocal function hook(...)\n"
        + SOURCE
        + "\nend\nhook("
        + arguments
        + ")\nassert(not suspended)\n"
        + assertions
    )
    result = subprocess.run([LUA, "-"], input=source, text=True, capture_output=True, timeout=5)
    assert result.returncode == 0, result.stderr


def test_probe_validates_all_keys_without_input_or_world_mutation():
    run(
        "",
        "'probe','/isolated','30','123','','SELECT','D_PAUSE'",
        """
assert(captured.ok and captured.keys_sent==0 and inputs==0)
assert(captured.command_mutation=='not_attempted')
assert(df.global.pause_state and df.global.cur_year_tick==123)
assert(captured.before.save_name=='fixture' and captured.after.save_name=='fixture')
""",
    )


def test_unknown_native_key_is_rejected_before_any_input():
    run(
        "",
        "'probe','/isolated','30','123','','SELECT','NO_SUCH_KEY'",
        """
assert(not captured.ok and captured.error=='unsupported_native_key')
assert(captured.invalid_key_index==2 and inputs==0)
assert(captured.command_mutation=='not_attempted')
""",
    )


def test_real_interface_selection_records_view_change_without_game_time():
    run(
        "",
        "'key','/isolated','30','123','fixture','SELECT'",
        """
assert(captured.ok and captured.keys_sent==1 and inputs==1)
assert(captured.command_mutation=='completed')
assert(captured.before.focus=='dwarfmode/Default' and captured.after.focus=='stocks')
assert(captured.after.year_tick==123 and captured.after.paused)
""",
    )


@pytest.mark.parametrize("failure", [False, True])
def test_pause_is_restored_inside_lock_even_when_input_throws(failure):
    run(
        f"input_failure={str(failure).lower()}",
        "'key','/isolated','30','123','fixture','D_PAUSE'",
        f"""
assert(captured.ok=={str(not failure).lower()} and inputs==1)
assert(captured.paused_after_input==false and captured.after.paused==true)
assert(df.global.pause_state and df.global.cur_year_tick==123)
assert(captured.command_mutation=='{"unknown" if failure else "completed"}')
""",
    )


@pytest.mark.parametrize("setup", ["change_clock=true", "change_save=true"])
def test_boundary_mutation_is_not_accepted_or_claimed_rolled_back(setup):
    run(
        setup,
        "'key','/isolated','30','123','fixture','SELECT'",
        """
assert(not captured.ok and inputs==1 and captured.keys_sent==1)
assert(captured.command_mutation=='unknown')
assert(captured.error=='keyboard_changed_native_boundary')
""",
    )


@pytest.mark.parametrize("setup", ["df.global.pause_state=false", "loaded=false"])
def test_unpaused_or_unloaded_game_receives_no_key(setup):
    run(
        setup,
        "'key','/isolated','30','123','fixture','SELECT'",
        """
assert(not captured.ok and inputs==0 and captured.command_mutation=='not_attempted')
""",
    )


@pytest.mark.parametrize(
    "arguments",
    [
        "'key','/other','30','123','fixture','SELECT'",
        "'key','/isolated','31','123','fixture','SELECT'",
        "'key','/isolated','30','124','fixture','SELECT'",
        "'key','/isolated','30','123','other','SELECT'",
        "'key','/isolated','30','123','fixture','SELECT','D_PAUSE'",
        "'key','/isolated','30','123','','SELECT'",
    ],
)
def test_mismatched_or_malformed_request_never_dispatches(arguments):
    run("", arguments, "assert(not captured.ok and inputs==0)")


def test_catalog_audits_every_key_without_inputs_and_reports_all_mismatches():
    run(
        "",
        "'catalog','/isolated','30','123','','SELECT','PAUSE','D_PAUSE','NONE'",
        """
assert(not captured.ok and inputs==0 and captured.keys_sent==0)
assert(captured.command_mutation=='not_attempted' and captured.checked==4)
assert(captured.supported[1]=='SELECT' and captured.supported[2]=='D_PAUSE')
assert(captured.unsupported[1]=='PAUSE' and captured.unsupported[2]=='NONE')
assert(captured.after.paused and captured.after.year_tick==123)
""",
    )


def test_catalog_accepts_more_than_one_hundred_names_but_key_mode_does_not():
    setup = "local names={} for i=1,1613 do names[i]='SELECT' end"
    run(
        setup,
        "'catalog','/isolated','30','123','',table.unpack(names)",
        "assert(captured.ok and captured.checked==1613 and inputs==0)",
    )
    run(
        setup,
        "'probe','/isolated','30','123','',table.unpack(names)",
        "assert(not captured.ok and inputs==0)",
    )
