"""One native map inspection fixture, with actual process-stop/save-load continuation."""

# The standalone container fixture imports only the pinned image checkout.
# ruff: noqa: E402

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

PROJECT = Path("/opt/fort-gym-campaign")
sys.path.insert(0, str(PROJECT))
from fort_gym.bench.agent.base import Agent
from fort_gym.bench.dfhack_exec import run_lua_expr
from fort_gym.bench.env.campaign_view import validate_map_read
from fort_gym.bench.run.campaign_advance import MODEL_REQUESTED
from fort_gym.bench.run.campaign_checkpoint import verify_checkpoint
from fort_gym.bench.run.campaign_loop import CampaignLoop, reconciled_usage
from fort_gym.bench.run.campaign_save import NativeSaveSnapshotter
from scripts.campaign_load_smoke import run_isolated, verify_snapshot
from scripts.campaign_process import run_worker, termination_as_interrupt

REVISION = "bbe58f9485d7ed42f288b9fa27f4d932159d9c01"
SEED_SHA = "eaf5fa5a40014719e6c313f33497740e536a8faa1c90a84c4e09dcc380ac0595"
OUT = Path("/evidence/map-inspection")
CHECKPOINT = OUT / "initial/checkpoint"
PROFILE = "campaign_state/v3"
POLICY = {"policy": "scripted-native-map-inspection/v3"}


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def boundary(state):
    assert state["pause_state"] is True
    return state["year"], state["year_tick"]


def guard(env):
    result = json.loads(
        run_lua_expr(
            """local j=require('json')
print(j.encode({year=df.global.cur_year, tick=df.global.cur_year_tick,
 paused=df.global.pause_state,
 camera={df.global.window_x,df.global.window_y,df.global.window_z},
 allocated_blocks=#df.global.world.map.map_blocks}))
""",
            timeout=5,
        )
    )
    screen = env.screen()
    result["screen_sha256"] = hashlib.sha256(screen.encode()).hexdigest()
    result["screen_text"] = screen
    result["viewscreen_type"] = env.observe()["viewscreen_type"]
    return result


def native_guard(value):
    # Rendering can change without a game action. Check native invariants, not pixels.
    return {
        key: value[key]
        for key in ("year", "tick", "paused", "camera", "allocated_blocks", "viewscreen_type")
    }


def visibility(selection):
    x, y, z = selection["origin"]
    width, height = selection["size"]
    # Selection is validated by the production parser before this independent
    # visibility-only probe. Never read hidden tile type, material or contents.
    result = json.loads(
        run_lua_expr(
            f"""
local j=require('json')
local rows={{}}
for y={y},{y + height - 1} do
 local row={{}}
 for x={x},{x + width - 1} do
  local b=dfhack.maps.getTileBlock(x,y,{z})
  local glyph='U'
  if b then
   local hidden=b.designation[x%16][y%16].hidden
   if type(hidden)=='boolean' then glyph=hidden and 'H' or 'V' end
  end
  table.insert(row,glyph)
 end
 table.insert(rows,table.concat(row))
end
print(j.encode({{rows=rows}}))
""",
            timeout=5,
        )
    )
    return result["rows"]


class FixtureAgent(Agent):
    def __init__(self):
        self.calls = 0
        self.campaign_id = None
        self.action = None
        self.last_observation = None

    def set_campaign_context(self, *, campaign_id):
        self.campaign_id = campaign_id

    def decide(self, text, observation):
        assert self.action is not None
        self.calls += 1
        self.last_observation = deepcopy(observation)
        return deepcopy(self.action)

    def export_campaign_state(self):
        return {
            "campaign_id": self.campaign_id,
            "configuration": POLICY,
            "memory": {"fixture_decisions": self.calls},
            "usage": {
                "total_tokens": 0,
                "total_cost_usd": "0",
                "returned_responses": 0,
                "accounted_responses": 0,
                "dispatched_requests": 0,
            },
        }

    def restore_campaign_state(self, state, *, campaign_id):
        assert self.campaign_id == campaign_id == state["campaign_id"]
        assert state["configuration"] == POLICY
        assert all(
            state["usage"][k] == 0
            for k in (
                "total_tokens",
                "returned_responses",
                "accounted_responses",
                "dispatched_requests",
            )
        )
        assert state["usage"]["total_cost_usd"] == "0"
        self.calls = state["memory"]["fixture_decisions"]


def checks(env, runtime, output, phase):
    initial = env.observe()
    assert boundary(initial) == (30, 16801)
    assert initial["viewscreen_type"] == "viewscreen_dwarfmodest"
    calls = {"world_dispatch": 0, "clock_dispatch": 0}

    def forbidden(kind):
        def reject(*args, **kwargs):
            calls[kind] += 1
            raise AssertionError("VIEW attempted " + kind)

        return reject

    env.executor.apply = forbidden("world_dispatch")
    env.client.advance = forbidden("clock_dispatch")
    agent = FixtureAgent()
    if phase == "initial":
        loop = CampaignLoop(
            campaign_id="scripted-map-inspection-native-v3",
            agent=agent,
            environment=env,
            output=output / "campaign",
            observation_profile=PROFILE,
            advance_policy=MODEL_REQUESTED,
        )
        dimensions = validate_map_read(env.inspect_map(None), None, initial)["map_dimensions"]
        anchor = initial["fort"]["map_origin"]
        assert len(anchor) == 3 and anchor[2] > 0
        assert anchor[0] + 8 <= dimensions[0] and anchor[1] + 8 <= dimensions[1]
        home = {"origin": anchor, "size": [8, 8]}
        selections = [
            home,
            {"origin": [0, 0, anchor[2]], "size": [8, 8]},
            {"origin": [anchor[0], anchor[1], anchor[2] - 1], "size": [8, 8]},
            {"origin": [n - 1 for n in dimensions], "size": [1, 1]},
            {"origin": [dimensions[0], 0, 0], "size": [1, 1]},
            home,
        ]
        assert selections[0]["origin"] != selections[1]["origin"]
    else:
        manifest = verify_checkpoint(CHECKPOINT)
        loop = CampaignLoop.resume(
            CHECKPOINT,
            agent=agent,
            environment=env,
            output=output / "campaign",
            latest_usage_path=OUT / "initial/campaign/usage.jsonl",
            observation_profile=PROFILE,
        )
        home = json.loads((CHECKPOINT / "runner.json").read_text())["observation_view"]
        assert loop.observation_view == home and loop.next_step == 6 and agent.calls == 6
        assert loop.committed_elapsed_ticks == 0
        selections = [home]
        dimensions = validate_map_read(env.inspect_map(None), None, initial)["map_dimensions"]
        assert manifest["payload"]["next_step"] == 6
    records = []
    for index, selection in enumerate(selections):
        previous = deepcopy(loop.observation_view)
        before = guard(env)
        control = guard(env)
        write(output / f"guard-{index}-before.json", {"before": before, "control": control})
        invalid = phase == "initial" and index == 4
        visible_before = None if invalid else visibility(selection)
        agent.action = {"type": "VIEW", "params": selection, "advance_ticks": 0}
        row = loop.step()
        assert row["execute"]["command_mutation"] == "not_attempted"
        assert row["execute"]["accepted"] is not invalid
        assert row["tick_advance"]["ticks_advanced"] == 0
        after_state = env.observe()
        after_guard = guard(env)
        write(
            output / f"guard-{index}-after.json",
            {
                "after": after_guard,
                "boundary": list(boundary(after_state)),
                "changed_fields": [key for key in before if before[key] != after_guard.get(key)],
            },
        )
        assert boundary(after_state) == (30, 16801)
        assert native_guard(after_guard) == native_guard(before) == native_guard(control)
        assert agent.last_observation["map_view"]["selection"] == previous
        assert calls == {"world_dispatch": 0, "clock_dispatch": 0}
        native = row["state_after_advance"]["map_view"]["native"]
        if invalid:
            assert row["execute"]["why"] == "view_rectangle_outside_map"
            assert loop.observation_view == previous
        else:
            assert loop.observation_view == selection
            assert visibility(selection) == visible_before
            assert native["map_origin"] == selection["origin"]
            assert native["map_size"] == selection["size"]
            assert native["hidden_tiles"] == sum(r.count("H") for r in visible_before)
            assert native["unreadable_tiles"] == sum(r.count("U") for r in visible_before)
            assert native["visible_tiles"] == sum(r.count("V") for r in visible_before)
            for masks, glyphs in zip(visible_before, native["map_rows"]):
                assert all(glyph == " " for mask, glyph in zip(masks, glyphs) if mask != "V")
        if phase == "initial" and index == 5:
            assert agent.last_observation["last_action_result"]["accepted"] is False
        records.append(
            {
                "selection": selection,
                "accepted": not invalid,
                "native": native,
                "guard_before": before,
                "native_guard_unchanged": True,
                "rendered_screen_unchanged": after_guard["screen_sha256"]
                == before["screen_sha256"],
                "control_rendered_screen_unchanged": control["screen_sha256"]
                == before["screen_sha256"],
                "visibility_mask": visible_before,
            }
        )
    assert loop.at_boundary and not loop.failed and loop.committed_elapsed_ticks == 0
    if phase == "initial":
        assert sum(r["native"].get("hidden_tiles", 0) for r in records if r["accepted"]) > 0
        manifest = loop.checkpoint(
            CHECKPOINT, snapshotter=NativeSaveSnapshotter(dfroot=runtime), code_revision=REVISION
        )
        assert verify_checkpoint(CHECKPOINT) == manifest
        assert boundary(env.observe()) == (30, 16801)
    else:
        assert agent.calls == 7 and loop.next_step == 7
        saved_native = json.loads((OUT / "initial/worker-result.json").read_text())["records"][-1][
            "native"
        ]
        assert records[0]["native"] == saved_native
    result = {
        "schema_version": "fortgym.native-map-inspection-worker/v1",
        "phase": phase,
        "source_revision": REVISION,
        "provider_calls": 0,
        "scripted": True,
        "autonomous_gameplay": False,
        "year_two_gameplay_verified": False,
        "records": records,
        "map_dimensions": dimensions,
        "dispatch_counts": calls,
        "total_actual_ticks": 0,
        "scripted_decisions_total": agent.calls,
        "next_step": loop.next_step,
        "checkpoint_sha256": sha(CHECKPOINT / "checkpoint.json"),
        "selected_view": loop.observation_view,
        "trace_sha256": sha(loop.trace),
        "usage_sha256": sha(loop.journal),
        "native_map_inspection_verified": True,
        "native_selection_continuation_verified": phase == "resume",
        "usage": reconciled_usage(agent.export_campaign_state(), loop.journal.read_bytes()),
    }
    write(output / "worker-result.json", result)
    return result


def worker(runtime, phase):
    from fort_gym.bench.run.campaign_environment import NativeCampaignEnvironment

    assert Path(os.environ["DFROOT"]).resolve() == runtime.resolve()
    env = NativeCampaignEnvironment(expected_dfroot=runtime)
    try:
        return checks(env, runtime, OUT / phase, phase)
    finally:
        env.close()


def main():
    assert (
        subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=PROJECT, text=True).strip()
        == REVISION
    )
    assert not subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=all"], cwd=PROJECT
    )
    if len(sys.argv) == 4 and sys.argv[1] == "--worker":
        print(json.dumps(worker(Path(sys.argv[2]), sys.argv[3])), flush=True)
        return
    assert len(sys.argv) == 1
    OUT.mkdir(mode=0o700, exist_ok=False)
    results = []
    for phase, port in (("initial", 5507), ("resume", 5508)):

        def perform(runtime, environment, loaded):
            worker_env = {
                **environment,
                "FORT_GYM_DISABLE_DOTENV": "1",
                "DFROOT": str(runtime),
                "DFHACK_ENABLED": "1",
                "DF_PROTO_ENABLED": "1",
                "DFHACK_HOST": "127.0.0.1",
                "DFHACK_PORT": str(port),
                "FORT_GYM_DFHACK_COMPLETE_DIG": "0",
                "ARTIFACTS_DIR": str(OUT / "unused-artifacts"),
                "FORT_GYM_DB_PATH": str(OUT / "unused-registry.sqlite"),
            }
            with (OUT / phase / "worker.log").open("x") as log:
                run_worker(
                    [
                        sys.executable,
                        str(Path(__file__).resolve()),
                        "--worker",
                        str(runtime),
                        phase,
                    ],
                    env=worker_env,
                    stdout=log,
                    timeout=300,
                )
            return json.loads((OUT / phase / "worker-result.json").read_text())

        with termination_as_interrupt():
            result = run_isolated(
                source=Path("/opt/dwarf-fortress"),
                snapshot=Path("/seed-evidence/seed-smoke") if phase == "initial" else CHECKPOINT,
                digest=SEED_SHA if phase == "initial" else sha(CHECKPOINT / "checkpoint.json"),
                source_kind="native_snapshot" if phase == "initial" else "campaign_checkpoint",
                output=OUT / phase,
                port=port,
                revision=REVISION,
                work=perform,
                hook_source=PROJECT / "hook",
                minimum_free_bytes=1073741824,
                checkpoint_copies=1 if phase == "initial" else 0,
            )
        assert result["cleanup_verified"] is True
        results.append(result)
    verify_snapshot(Path("/seed-evidence/seed-smoke"), SEED_SHA)
    write(
        OUT / "result.json",
        {
            "schema_version": "fortgym.native-map-inspection-fixture/v1",
            "source_revision": REVISION,
            "native_map_inspection_verified": True,
            "native_selection_continuation_verified": True,
            "cleanup_verified": True,
            "provider_calls": 0,
            "autonomous_gameplay": False,
            "year_two_gameplay_verified": False,
            "total_actual_ticks": 0,
            "original_seed_unchanged": True,
            "phases": results,
        },
    )
    print(
        json.dumps(
            {
                "native_map_inspection_verified": True,
                "native_selection_continuation_verified": True,
                "native_cleanup_verified": True,
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
