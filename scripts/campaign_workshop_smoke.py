"""Provider-free workshop adapter fixture on one caller-owned copied save.

Selects visible fixture coordinates, requests bounded native time, and attempts
woodcutting/construction. No item injection, instant completion, model calls, or
human rescue of a model campaign. Its final save must not seed a matched model
comparison. The launcher always tears down its own isolated runtime.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.campaign_load_smoke import run_isolated
from scripts.campaign_process import run_worker, termination_as_interrupt
from scripts.campaign_segment import write_result

FIXTURE_SCAN = """
local out={version=dfhack.getDFHackVersion(), wood={total=0,free_flags=0,in_building=0},trees={}}
local shapes={FLOOR=true,BOULDER=true,PEBBLES=true,TWIG=true,SAPLING=true,SHRUB=true}
for _,item in ipairs(df.global.world.items.all) do
  if item:getType()==df.item_type.WOOD then
    out.wood.total=out.wood.total+1
    if item.flags.in_building then out.wood.in_building=out.wood.in_building+1 end
    local unavailable=false
    for _,key in ipairs({'garbage_collect','in_job','forbid','hidden','in_inventory',
        'in_building','construction','artifact','dump','hostile','on_fire','rotten',
        'trader','owned','removed','encased'}) do
      if item.flags[key] then unavailable=true end
    end
    if not unavailable then out.wood.free_flags=out.wood.free_flags+1 end
  end
end
local origin
for _,unit in ipairs(df.global.world.units.active) do
  if dfhack.units.isCitizen(unit) and not dfhack.units.isDead(unit) then origin=unit.pos; break end
end
assert(origin,'fixture requires a living citizen')
local function tile(x,y,z)
  local block=dfhack.maps.getTileBlock(x,y,z)
  if not block then return nil end
  local dx,dy=x%16,y%16
  local flags=block.designation[dx][dy]
  if flags.hidden then return nil end
  return df.tiletype.attrs[block.tiletype[dx][dy]],flags,block.occupancy[dx][dy]
end
for radius=0,24 do
  for x=origin.x-radius,origin.x+radius do
    for y=origin.y-radius,origin.y+radius do
      if math.max(math.abs(x-origin.x),math.abs(y-origin.y))==radius then
        local attr=tile(x,y,origin.z)
        if attr and attr.shape==df.tiletype_shape.WALL and attr.material==df.tiletype_material.TREE
            and #out.trees<3 then table.insert(out.trees,{x,y,origin.z}) end
        if radius<=8 and not out.workshop then
          local valid,broad,count=true,false,{}
          for tx=x,x+2 do for ty=y,y+2 do
            local a,f,o=tile(tx,ty,origin.z)
            local shape=a and df.tiletype_shape[a.shape] or ''
            if not a or not shapes[shape] or o.building~=0 or f.flow_size>0
                or a.material==df.tiletype_material.FROZEN_LIQUID then valid=false end
            if shape~='FLOOR' then broad=true end
            count[shape]=(count[shape] or 0)+1
          end end
          if valid and broad then out.workshop={x=x,y=y,z=origin.z,shapes=count} end
        end
      end
    end
  end
end
print(require('json').encode(out))
"""


def worker(output: Path) -> dict:
    from fort_gym.bench.dfhack_backend import build_workshop
    from fort_gym.bench.dfhack_exec import run_lua_expr
    from fort_gym.bench.env.workshop_placement import NATIVE_GROUND
    from fort_gym.bench.run.campaign_advance import MODEL_REQUESTED, requested_ticks
    from fort_gym.bench.run.campaign_environment import NativeCampaignEnvironment
    from fort_gym.bench.run.campaign_save import NativeSaveSnapshotter
    from fort_gym.bench.tick_receipt import calendar_elapsed_ticks

    runtime = output.resolve() / "runtime"
    if Path(os.environ["DFROOT"]).resolve() != runtime:
        raise ValueError("Fixture worker DFROOT is not its isolated runtime")
    environment = NativeCampaignEnvironment(
        expected_dfroot=runtime, workshop_placement_policy=NATIVE_GROUND
    )
    result = {
        "schema_version": "fortgym.native-workshop-smoke/v1",
        "autonomous_gameplay": False,
        "provider_calls": 0,
        "metered_model_api_charges_usd": "0",
        "workshop_placement_policy": NATIVE_GROUND,
        "terrain_predicate_verified": False,
        "workshop_complete": False,
        "actions": [],
    }

    def scan():
        environment._verify_runtime()
        return json.loads(run_lua_expr(FIXTURE_SCAN, timeout=10))

    def command(kind, params, ticks):
        before = environment.observe()
        action = {"type": kind, "params": params, "advance_ticks": ticks}
        execution = environment.apply(action, before)
        requested = requested_ticks(ticks, execution, MODEL_REQUESTED)
        after, receipt = environment.advance(requested, before)
        elapsed, error = calendar_elapsed_ticks(
            before["year"], before["year_tick"], after["year"], after["year_tick"]
        )
        row = dict(action=action, execution=execution, ticks=receipt, actual_ticks=elapsed)
        result["actions"].append(row)
        write_result(output / f"action-{len(result['actions']):02}.json", row)
        if error is not None or receipt.get("ok") is not True or elapsed != requested:
            raise ValueError("Fixture did not establish the requested native clock boundary")
        return execution, after

    try:
        result["initial"] = environment.observe()
        result["initial_material_scan"] = scan()
        if result["initial_material_scan"]["version"] != "0.47.05-r8":
            raise ValueError("Fixture is pinned to the installed DFHack 0.47.05-r8 rules")
        command("WAIT", {}, 10)  # Explicit fixture time, never a model fallback.
        candidates = scan()
        result["fixture_candidates"] = candidates
        target = candidates.get("workshop")
        if target is None:
            raise ValueError("No visible non-FLOOR ground fixture footprint found")
        params = {"kind": "CarpenterWorkshop", **{k: target[k] for k in ("x", "y", "z")}}
        legacy = build_workshop(**params)
        result["legacy_control"] = legacy
        if (
            legacy.get("error") != "tile_not_open_floor"
            or legacy.get("command_mutation") != "not_attempted"
        ):
            raise ValueError("Legacy control did not reject terrain before mutation")
        placement, _ = command("BUILD", params, 0)
        result["terrain_predicate_verified"] = placement.get("accepted") is True or placement.get(
            "why"
        ) in {
            "no_building_material",
            "no_reachable_building_material",
        }
        if not result["terrain_predicate_verified"]:
            return result
        if placement.get("accepted") is not True:
            if not candidates["trees"]:
                raise ValueError("No visible tree fixture found")
            cut, _ = command(
                "DIG", {"area": candidates["trees"][0], "size": [1, 1, 1], "kind": "chop"}, 2000
            )
            if cut.get("accepted") is not True:
                return result
            for _ in range(8):
                if scan()["wood"]["free_flags"]:
                    break
                command("WAIT", {}, 2000)
            placement, _ = command("BUILD", params, 2000)
        if placement.get("accepted") is True:
            for _ in range(8):
                current = environment.observe()
                if current.get("work", {}).get("carpenter_workshops_usable", 0) > 0:
                    result["workshop_complete"] = True
                    break
                command("WAIT", {}, 2000)
        return result
    except Exception as error:
        result.update(error_type=type(error).__name__, error=str(error))
        raise
    finally:
        try:
            result["final"] = environment.observe()
            result["final_material_scan"] = scan()
            result["final_snapshot"] = NativeSaveSnapshotter(dfroot=runtime).capture(
                output / "final-save"
            )
        finally:
            try:
                write_result(output / "worker-result.json", result)
            finally:
                environment.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--snapshot-sha256")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=5600)
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    if args.worker:
        worker(args.output)
        return
    if args.source is None or args.snapshot is None or args.snapshot_sha256 is None:
        parser.error("source, snapshot and snapshot-sha256 are required")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"]):
        raise ValueError("Run native acceptance from a clean committed checkout")

    def play(runtime, environment, loaded):
        worker_env = {
            **environment,
            "FORT_GYM_DISABLE_DOTENV": "1",
            "OPENROUTER_API_KEY": "",
            "DFROOT": str(runtime),
            "DFHACK_HOST": "127.0.0.1",
            "DFHACK_PORT": str(args.port),
            "DFHACK_ENABLED": "1",
            "DF_PROTO_ENABLED": "1",
            "FORT_GYM_DFHACK_COMPLETE_DIG": "0",
            "ARTIFACTS_DIR": str(args.output.resolve() / "unused-artifacts"),
            "FORT_GYM_DB_PATH": str(args.output.resolve() / "unused-registry.sqlite"),
        }
        with (args.output / "worker.log").open("xb") as stream:
            run_worker(
                [
                    sys.executable,
                    "-m",
                    "scripts.campaign_workshop_smoke",
                    "--worker",
                    "--output",
                    str(args.output.resolve()),
                ],
                env=worker_env,
                stdout=stream,
                timeout=600,
            )
        data = json.loads((args.output / "worker-result.json").read_text())
        return {
            key: data[key]
            for key in (
                "provider_calls",
                "autonomous_gameplay",
                "terrain_predicate_verified",
                "workshop_complete",
            )
        }

    with termination_as_interrupt():
        result = run_isolated(
            source=args.source,
            snapshot=args.snapshot,
            digest=args.snapshot_sha256,
            output=args.output,
            port=args.port,
            revision=revision,
            work=play,
            hook_source=Path(__file__).resolve().parents[1] / "hook",
        )
    print(
        json.dumps(
            {"experiment": result["experiment"], "cleanup_verified": result["cleanup_verified"]}
        )
    )


if __name__ == "__main__":
    main()
