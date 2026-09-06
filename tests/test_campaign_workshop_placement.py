"""Versioned workshop policy tests; Lua doubles do not establish native acceptance."""

import json
from copy import deepcopy

import pytest

from fort_gym.bench import dfhack_backend
from fort_gym.bench.env import executor as executor_module
from fort_gym.bench.env.campaign_encoder import encode_campaign_observation
from fort_gym.bench.env.workshop_placement import (
    GROUND_SHAPES,
    NATIVE_GROUND,
    STRICT_FLOOR,
    policy_observation,
)
from fort_gym.bench.run.campaign_config import load_segment_config
from tests.test_campaign_local import CONFIG, MODEL, policy
from tests.test_native_action_receipts import LUA, run_hook


def test_backend_default_preserves_legacy_arguments_and_new_policy_is_explicit(monkeypatch):
    calls = []
    monkeypatch.setattr(
        dfhack_backend, "run_lua_file", lambda *a, **kw: calls.append(a) or {"ok": True}
    )
    for value in (STRICT_FLOOR, NATIVE_GROUND):
        assert dfhack_backend.build_workshop("Still", 1, 2, 3, placement_policy=value)["ok"]
    assert calls[0][1:] == ("Still", "1", "2", "3")
    assert calls[1][1:] == ("Still", "1", "2", "3", NATIVE_GROUND)
    assert dfhack_backend.build_workshop("Still", 1, 2, 3, placement_policy="unknown") == {
        "ok": False,
        "error": "invalid_workshop_placement_policy",
        "command_mutation": "not_attempted",
    }
    assert len(calls) == 2


@pytest.mark.parametrize("kind", ["CarpenterWorkshop", "Still", "Bed"])
def test_executor_routes_ground_policy_only_to_workshops(monkeypatch, kind):
    calls = []
    monkeypatch.setattr(executor_module, "validate_action", lambda *a: (True, None))
    for helper in ("safe_build_workshop", "safe_place_furniture"):
        monkeypatch.setattr(
            executor_module, helper, lambda *a, **kw: calls.append((a, kw)) or {"ok": True}
        )
    executor = executor_module.Executor(
        dfhack_client=object(), workshop_placement_policy=NATIVE_GROUND
    )
    result = executor.apply(
        {"type": "BUILD", "params": {"kind": kind, "x": 1, "y": 2, "z": 3}},
        backend="dfhack",
        state={"pause_state": True},
    )
    assert result["accepted"] is True
    assert calls == [
        ((kind, 1, 2, 3), {} if kind == "Bed" else {"placement_policy": NATIVE_GROUND})
    ]


@pytest.mark.parametrize("value", [False, None, [], {}, "unknown/v1"])
def test_invalid_policy_rejected_before_campaign_execution(tmp_path, value):
    config = json.loads(CONFIG.read_text())
    config["workshop_placement_policy"] = value
    path = tmp_path / "condition.json"
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="workshop placement policy"):
        load_segment_config(path, MODEL)


def test_policy_is_factual_model_visible_and_checkpoint_identity_cannot_change(tmp_path):
    config = load_segment_config(CONFIG, MODEL)
    state = policy(config, tmp_path).export_campaign_state()
    changed = deepcopy(config)
    changed["workshop_placement_policy"] = NATIVE_GROUND
    with pytest.raises(ValueError, match="configuration"):
        policy(changed, tmp_path).restore_campaign_state(state, campaign_id="local-test")
    text, observed = encode_campaign_observation(
        {"workshop_placement": policy_observation()},
        screen_text="test-only",
        action_history=[],
        last_action_result=None,
    )
    assert observed["workshop_placement"]["allowed_ground_shapes"] == list(GROUND_SHAPES)
    assert NATIVE_GROUND in text
    assert "completed workshop" in text and "Other BUILD kinds" in text


def test_ground_condition_preserves_all_other_execution_settings():
    prior = load_segment_config(CONFIG.with_name("local_native_harness_repair_v1.json"), MODEL)
    changed = load_segment_config(CONFIG.with_name("local_native_workshop_ground_v1.json"), MODEL)
    assert changed.pop("workshop_placement_policy") == NATIVE_GROUND
    for name in ("condition_id", "hypothesis", "notes"):
        prior.pop(name)
        changed.pop(name)
    assert changed == prior


GROUND_SETUP = """
df.global.world = {reindex_pathfinding=false, buildings={all={}}, items={all={}},
                  units={active={{pos={x=1,y=2,z=3}}}}}
df.tiletype_shape, df.tiletype_material, df.job_type = enum, enum, enum
local attr = {shape=SHAPE,material='SOIL'}
df.tiletype = {attrs={test=attr},test='test'}
local block = {designation={}, occupancy={}, tiletype={}}
for x=0,15 do
  block.designation[x],block.occupancy[x],block.tiletype[x] = {},{},{}
  for y=0,15 do
    block.designation[x][y] = {hidden=false,flow_size=0}
    block.occupancy[x][y] = {building=0}
    block.tiletype[x][y] = 'test'
  end
end
dfhack = {
  maps={getTileBlock=function() return block end, canWalkBetween=function() return true end},
  units={isCitizen=function() return true end, isDead=function() return false end,
         getPosition=function(u) return u.pos.x,u.pos.y,u.pos.z end},
  items={getPosition=function() return 1,2,3 end},
}
"""


def ground_hook(shape, placement, *, setup="", assertions=""):
    run_hook(
        "build_workshop.lua",
        ["CarpenterWorkshop", 1, 2, 3, placement],
        setup="local SHAPE=" + json.dumps(shape) + "\n" + GROUND_SETUP + setup,
        assertions=assertions,
    )


@pytest.mark.skipif(LUA is None, reason="Lua interpreter is unavailable")
@pytest.mark.parametrize("shape", GROUND_SHAPES)
def test_native_ground_shapes_reach_material_checks_but_legacy_remains_floor_only(shape):
    for placement in (STRICT_FLOOR, NATIVE_GROUND):
        expected = (
            "no_building_material"
            if shape == "FLOOR" or placement == NATIVE_GROUND
            else "tile_not_open_floor"
        )
        ground_hook(
            shape,
            placement,
            assertions=f"""
assert(captured.ok == false and captured.error == '{expected}', captured.error)
assert(captured.command_mutation == 'not_attempted')
assert(captured.workshop_placement_policy == {json.dumps(NATIVE_GROUND) if placement == NATIVE_GROUND else 'nil'})
""",
        )


@pytest.mark.skipif(LUA is None, reason="Lua interpreter is unavailable")
@pytest.mark.parametrize("shape", ["WALL", "EMPTY", "RAMP", "STAIR_UP", "TREE", "UNKNOWN"])
def test_other_shapes_remain_rejected(shape):
    ground_hook(
        shape,
        NATIVE_GROUND,
        assertions="assert(captured.error == 'tile_not_workshop_ground' and captured.failed_count == 9)",
    )


@pytest.mark.skipif(LUA is None, reason="Lua interpreter is unavailable")
@pytest.mark.parametrize(
    "setup,error",
    [
        ("block.designation[3][4].hidden=true", "tile_hidden_unexplored"),
        ("block.occupancy[3][4].building=1", "tile_occupied_by_building"),
        ("block.designation[3][4].flow_size=1", "tile_has_liquid"),
        ("attr.material='FROZEN_LIQUID'", "tile_frozen_liquid"),
        (
            "dfhack.maps.canWalkBetween=function() return false end",
            "workshop_unreachable_from_citizens",
        ),
        ("df.global.world.reindex_pathfinding=true", "path_cache_stale"),
    ],
)
def test_ground_policy_preserves_each_existing_guard(setup, error):
    ground_hook(
        "SHRUB",
        NATIVE_GROUND,
        setup=setup,
        assertions=f"assert(captured.error == '{error}' and captured.command_mutation == 'not_attempted', captured.error)",
    )


@pytest.mark.skipif(LUA is None, reason="Lua interpreter is unavailable")
@pytest.mark.parametrize("in_building", [False, True])
def test_native_ground_requires_a_free_material_and_attached_normal_construction_job(in_building):
    ground_hook(
        "BOULDER",
        NATIVE_GROUND,
        setup="""
local material = {id=7, flags={in_building=IN_BUILDING},
                  getType=function() return 'WOOD' end, isBuildMat=function() return true end}
df.global.world.items.all = {material}
local dispatched=false
package.preload['dfhack.buildings'] = function() return {constructBuilding=function(options)
  assert(options.items[1] == material and options.width == 3 and options.height == 3)
  dispatched=true
  return {id=8, construction_stage=0,
          jobs={{job_type='ConstructBuilding',items={{item=material}}}}}
end} end
""".replace(
            "IN_BUILDING", str(in_building).lower()
        ),
        assertions=(
            "assert(captured.error == 'no_building_material' and not dispatched)"
            if in_building
            else "assert(captured.ok == true and dispatched and captured.jobs_count == 1 and captured.construction_stage == 0)"
        ),
    )
