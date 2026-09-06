"""Execute hook control flow in Lua with explicit engine doubles, not native DF."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1] / "hook"
LUA = shutil.which("lua")
pytestmark = pytest.mark.skipif(LUA is None, reason="Lua interpreter is unavailable")

PRELUDE = """
local captured
package.preload.json = function() return {encode = function(value) captured = value; return 'receipt' end} end
for _, name in ipairs({'dfhack.buildings', 'dfhack.workshops', 'utils'}) do
  package.preload[name] = function() return {} end
end
local enum = setmetatable({}, {__index = function(_, key) return key end})
df = {workshop_type=enum, item_type=enum, building_type=enum, construction_type=enum,
      unit_labor=enum, profession=enum, global={world={reindex_pathfinding=true}}}
print = function() end
"""


def run_hook(name, args, *, setup="", assertions=""):
    arguments = ", ".join(json.dumps(value) for value in args)
    code = PRELUDE + setup + f"\nassert(loadfile(arg[1]))({arguments})\n" + assertions
    result = subprocess.run(
        [LUA, "-", str(HOOKS / name)], input=code, text=True, capture_output=True, timeout=5
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "name",
    [
        "designate_rect.lua",
        "build_workshop.lua",
        "build_construction.lua",
        "build_farm_plot.lua",
        "place_furniture.lua",
        "order_make.lua",
        "set_labor.lua",
        "set_farm_crop.lua",
        "unsuspend_jobs.lua",
    ],
)
def test_every_hook_marks_pre_dispatch_argument_rejection(name):
    run_hook(
        name,
        [],
        assertions="assert(captured.ok == false and captured.command_mutation == 'not_attempted')",
    )


@pytest.mark.parametrize(
    "name,kind",
    [
        ("build_workshop.lua", "CarpenterWorkshop"),
        ("build_construction.lua", "Wall"),
        ("place_furniture.lua", "Bed"),
    ],
)
def test_stale_path_cache_is_attested_without_changing_native_flag(name, kind):
    run_hook(
        name,
        [kind, 1, 2, 3],
        assertions="""
assert(captured.error == 'path_cache_stale' and captured.command_mutation == 'not_attempted')
assert(df.global.world.reindex_pathfinding == true)
""",
    )


def test_failure_after_one_unsuspend_is_not_mislabeled_as_preflight():
    run_hook(
        "unsuspend_jobs.lua",
        [1, 2, 3, 1, 2, 3],
        setup="""
local job = {flags={suspend=true}, pos={x=1,y=2,z=3}}
local link = setmetatable({item=job}, {__index=function() error('injected list read failure') end})
df.global.world.jobs = {list={next=link}}
""",
        assertions="""
assert(captured.ok == false and captured.error == 'job_list_unavailable')
assert(captured.command_mutation == 'attempted' and job.flags.suspend == false)
""",
    )


def test_unsuspend_read_failure_before_any_write_is_preflight():
    run_hook(
        "unsuspend_jobs.lua",
        [1, 2, 3, 1, 2, 3],
        assertions="""
assert(captured.error == 'job_list_unavailable' and captured.command_mutation == 'not_attempted')
""",
    )


def test_labor_write_failure_is_not_mislabeled_even_after_verified_rollback():
    run_hook(
        "set_labor.lua",
        [7, "mine", "true"],
        setup="""
local labors = setmetatable({}, {
  __index=function() return false end,
  __newindex=function(_, _, value) if value then error('injected write failure') end end,
})
df.global.world.units = {active={{id=7, profession=1, status={labors=labors}}}}
dfhack = {units={isCitizen=function() return true end, isAdult=function() return true end}}
""",
        assertions="""
assert(captured.ok == false and captured.error == 'labor_write_failed')
assert(captured.rollback_verified == true and captured.command_mutation == 'attempted')
""",
    )
