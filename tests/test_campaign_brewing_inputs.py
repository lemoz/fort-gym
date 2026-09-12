"""Execute the shipped campaign scanner with material/stack doubles, not a game."""

from pathlib import Path
import shutil
import subprocess

import pytest

LUA = shutil.which("lua")
HOOK = Path(__file__).resolve().parents[1] / "hook/campaign_job_metrics_v1.lua"
SOURCE = (
    HOOK.read_text()
    .split("-- Raw production inputs.", 1)[1]
    .split("-- placed furniture buildings", 1)[0]
)
# Keep the remainder of the first comment a comment when extracting this block.
SOURCE = "-- Raw production inputs." + SOURCE
PRELUDE = """
local out = {}
local items = {}
df = {global={world={items={other={IN_PLAY=items}}}},item_type={[1]='PLANT',[2]='DRINK',[3]='BARREL'}}
dfhack = {matinfo={decode=function(item) return item.material end},
  items={getContainedItems=function(item) return item.contents end}}
local function plant(units, products, alcohol)
  local value = {getType=function() return 1 end, getStackSize=function() return units end,
    stack_size=999, flags={in_job=false}, material={material={flags={ALCOHOL_PLANT=alcohol or false},
      reaction_product={id=products or {{value='DRINK_MAT'}}}}}}
  table.insert(items,value)
  return value
end
"""


def run(setup, assertions):
    if LUA is None:
        pytest.skip("Lua interpreter is unavailable")
    result = subprocess.run(
        [LUA, "-"],
        input=PRELUDE + setup + "\n" + SOURCE + "\n" + assertions,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr


def test_plant_reaction_product_not_finished_alcohol_flag_determines_ingredient():
    run(
        "plant(7); plant(5,{'SEED_MAT','DRINK_MAT'}); plant(99,{},true)",
        """
assert(out.production_inputs.schema_version=='fortgym.campaign-production-inputs/v2')
assert(out.production_inputs.brewable_plant_scan_complete)
assert(out.production_inputs.brewable_plant_stacks==2)
assert(out.production_inputs.brewable_plant_units==12)
assert(out.production_inputs.brewable_plant_read_failures==0)
assert(items[1].stack_size==999 and items[1].material.material.flags.ALCOHOL_PLANT==false)
""",
    )


def test_assigned_stacks_are_separate_from_unassigned_units_and_zero_is_known():
    run(
        "plant(7).flags.in_job=true; plant(0)",
        """
assert(out.production_inputs.brewable_plant_scan_complete)
assert(out.production_inputs.brewable_plant_stacks_in_jobs==1)
assert(out.production_inputs.brewable_plant_stacks==1)
assert(out.production_inputs.brewable_plant_units==0)
assert(items[1].flags.in_job)
""",
    )


def test_empty_and_nonbrewable_inventories_are_confirmed_zero():
    run(
        "plant(5,{})",
        """
assert(out.production_inputs.brewable_plant_scan_complete)
assert(out.production_inputs.brewable_plant_units==0)
assert(out.production_inputs.brewable_plant_stacks==0)
""",
    )


@pytest.mark.parametrize(
    "setup",
    [
        "plant(5).material=nil",
        "plant(5).material.material.reaction_product=nil",
        "plant(5).material.material.reaction_product.id=nil",
        "plant(5).material.material.reaction_product.id={{value=false}}",
        "plant(5).getType=function() error('unreadable type') end",
        "plant(5).getType=function() return 99 end",
        "plant(5).flags=nil",
        "plant(5).flags.in_job=nil",
        "plant(5).flags.in_job=1",
        "plant(5).getStackSize=function() error('unreadable stack') end",
        "plant(9007199254740991)",
        *[
            f"plant({value})"
            for value in ("-1", "1.5", "'5'", "true", "math.huge", "0/0", "nil")
        ],
    ],
)
def test_incomplete_classification_never_becomes_zero_or_a_partial_total(setup):
    run(
        "plant(3); " + setup,
        """
assert(not out.production_inputs.brewable_plant_scan_complete)
assert(out.production_inputs.brewable_plant_read_failures==1)
assert(out.production_inputs.brewable_plant_stacks==nil)
assert(out.production_inputs.brewable_plant_units==nil)
assert(out.production_inputs.brewable_plant_stacks_in_jobs==nil)
""",
    )


def test_drink_and_barrel_classification_are_not_plant_ingredients():
    run(
        """
table.insert(items,{getType=function() return 2 end})
table.insert(items,{getType=function() return 3 end, flags={in_job=false},contents={}})
""",
        """
assert(out.production_inputs.brewable_plant_scan_complete)
assert(out.production_inputs.brewable_plant_units==0)
assert(out.production_inputs.total_barrels==1 and out.production_inputs.empty_barrels==1)
""",
    )
