"""Provider-free fresh reload of the completed Year-Two displayed-key save."""

# ruff: noqa: E402 -- the injected container fixture selects the pinned project first.

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

PROJECT = Path("/opt/fort-gym-campaign")
sys.path.insert(0, str(PROJECT))

from fort_gym.bench.agent.campaign_keyboard import CodexKeyboardAgent
from fort_gym.bench.agent.keyboard_exchange import publish, read
from fort_gym.bench.env.campaign_binding_keys import execute_binding_keys, read_binding_index
from fort_gym.bench.eval.campaign_profile import metrics_from_state
from fort_gym.bench.run.campaign_checkpoint import verify_checkpoint
from fort_gym.bench.run.campaign_loop import CampaignLoop, _clock
from fort_gym.bench.run.campaign_resources import capture_resources
from scripts.campaign_keyboard_native import verify_source
from scripts.campaign_load_smoke import run_isolated
from scripts.campaign_process import run_worker, termination_as_interrupt

REVISION = "d22f28d99f4fd103188979e964e148139d3f3efd"
CHECKPOINT = Path("/previous-evidence/astra/segment-4/checkpoint")
LATEST_USAGE = Path("/previous-evidence/astra/segment-4/loop/usage.jsonl")
OUTPUT = Path("/evidence/binding-checkpoint416-reload")
PORT = 5612
MANIFEST = "73f90e9bb9097fe00ed056723c0cc8de36bb0b85b4c0e40878af86d071c7704a"
FILE_SHA = "9de235fa8e7ab30684c2b82424967b5b505b7951f048118f6915d64c2a513ec9"
EXPECTED_METRICS = {
    "completed_beds": 12,
    "completed_farms": 1,
    "completed_workshops": 3,
    "drink_stock": 389,
    "food_stock": 43,
    "functional_rooms": None,
    "population": 13,
    "recorded_dead_citizens": 0,
    "stone_stock": None,
    "wood_stock": None
}


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def source():
    manifest = verify_checkpoint(CHECKPOINT)
    assert manifest["sha256"] == MANIFEST and sha(CHECKPOINT / "checkpoint.json") == FILE_SHA
    assert manifest["payload"]["next_step"] == 416
    assert manifest["payload"]["campaign_id"] == "bindings-20260911-astra-r1"
    assert LATEST_USAGE.read_bytes() == (CHECKPOINT / "usage.jsonl").read_bytes()
    return manifest


def forbidden(*args, **kwargs):
    raise AssertionError("No model invocation, gameplay action or time advance is allowed")


def probe(runtime):
    result = execute_binding_keys([], expected_dfroot=runtime, year=31, year_tick=43446)
    assert result["accepted"] is True
    execution = result["result"]
    assert execution["keys_sent"] == execution["keys_confirmed"] == 0
    assert execution["command_mutation"] == "not_attempted"
    assert execution["native_receipts"] == []
    return result


def inspect(runtime):
    from fort_gym.bench.run.campaign_environment import NativeCampaignEnvironment

    manifest = source()
    original, runner = read(CHECKPOINT / "agent.json"), read(CHECKPOINT / "runner.json")
    condition = read(PROJECT / "experiments/keyboard_bindings_20260911/astra-condition.json")
    environment = NativeCampaignEnvironment(
        expected_dfroot=runtime,
        control_profile=condition["control_profile"],
        max_advance_ticks=condition["max_advance_ticks"],
        private_measurement_profile="fortgym.campaign-food-measurement/v1",
        private_measurement_timeout_seconds=15,
    )
    environment.apply = forbidden
    environment.advance = forbidden
    try:
        before, screen = environment.observe(), environment.screen_capture()
        publish(OUTPUT / "native-before.json", before)
        publish(OUTPUT / "screen.json", screen)
        assert [screen["width"], screen["height"]] == condition["screen_size"] == [120, 40]
        assert before["pause_state"] is True and _clock(before) == 31 * 403200 + 43446
        assert metrics_from_state(before) == EXPECTED_METRICS
        binding = read_binding_index(runtime)
        assert binding.sha256 == condition["bindings_sha256"]
        probe_before = probe(runtime)
        publish(OUTPUT / "binding-probe-before.json", probe_before)
        agent = CodexKeyboardAgent(
            decision=forbidden,
            **{
                key: original["configuration"][key]
                for key in (
                    "max_dispatches",
                    "max_total_tokens",
                    "max_advance_ticks",
                    "model",
                    "reasoning_effort",
                    "control_profile",
                )
            },
        )
        loop = CampaignLoop.resume(
            CHECKPOINT,
            agent=agent,
            environment=environment,
            output=OUTPUT / "restored-loop",
            latest_usage_path=LATEST_USAGE,
            observation_profile=condition["observation_profile"],
            advance_policy=condition["advance_policy"],
        )
        assert agent.export_campaign_state() == original
        assert agent.prompt_profile == condition["prompt_profile"]
        assert loop.next_step == 416 and loop.committed_elapsed_ticks == 429845
        assert loop.history == runner["history"] and loop.last_result == runner["last_result"]
        assert loop.discontinuities == runner.get("discontinuities", [])
        assert loop.trace.read_bytes() == (CHECKPOINT / "trace.jsonl").read_bytes()
        assert loop.journal.read_bytes() == LATEST_USAGE.read_bytes()
        after, probe_after = environment.observe(), probe(runtime)
        assert after["pause_state"] is True and _clock(after) == _clock(before)
        assert metrics_from_state(after) == EXPECTED_METRICS
        assert source() == manifest and read(CHECKPOINT / "agent.json") == original
        publish(OUTPUT / "native-after.json", after)
        publish(OUTPUT / "binding-probe-after.json", probe_after)
        publish(OUTPUT / "agent-restored.json", deepcopy(agent.export_campaign_state()))
        saved_menu = manifest["payload"]["native_save"]["save_operation"]["ui_after"]["focus"]
        loaded_menu = probe_before["result"]["boundary_probe"]["result"]["native_receipts"][-1][
            "after"
        ]["focus"]
        result = {
            "schema_version": "fortgym.private-binding-checkpoint-reload-inspection/v1",
            "passed": True,
            "source_revision": REVISION,
            "checkpoint_sha256": MANIFEST,
            "paused_year": 31,
            "paused_year_tick": 43446,
            "next_step": 416,
            "committed_elapsed_ticks": 429845,
            "actual_screen_size": [120, 40],
            "normal_loop_restore_verified": True,
            "agent_unchanged": True,
            "trace_usage_history_unchanged": True,
            "original_checkpoint_unchanged": True,
            "bindings_sha256": binding.sha256,
            "saved_metrics": EXPECTED_METRICS,
            "usage": original["usage"],
            "saved_menu_focus": saved_menu,
            "loaded_menu_focus": loaded_menu,
            "menu_focus_equal": saved_menu == loaded_menu,
            "full_menu_equivalence_claimed": False,
            "manual_menu_restoration": False,
            "model_calls": 0,
            "gameplay_actions": 0,
            "gameplay_ticks_requested": 0,
            "observed_elapsed_ticks": 0,
            "native_saves_requested": 0,
            "autonomous_gameplay": False,
            "year_two_success": False,
            "resources": capture_resources(),
        }
        publish(OUTPUT / "inspection.json", result)
        return result
    finally:
        environment.close()


def run():
    verify_source(REVISION)
    source()
    OUTPUT.mkdir(mode=0o700, exist_ok=False)
    result = {
        "schema_version": "fortgym.private-binding-checkpoint-native-reload/v1",
        "source_revision": REVISION,
        "checkpoint_sha256": MANIFEST,
        "driver_sha256": sha(Path(__file__)),
        "status": "failed",
        "model_calls": 0,
        "gameplay_actions": 0,
        "native_saves_requested": 0,
        "new_campaign_checkpoint": False,
        "autonomous_gameplay": False,
        "resource_before": capture_resources(),
    }
    publish(OUTPUT / "launch.json", result)

    def work(runtime, environment, loaded):
        worker_env = {
            **environment,
            "FORT_GYM_DISABLE_DOTENV": "1",
            "DFROOT": str(runtime),
            "DFHACK_ENABLED": "1",
            "DF_PROTO_ENABLED": "1",
            "DFHACK_HOST": "127.0.0.1",
            "DFHACK_PORT": str(PORT),
            "FORT_GYM_DFHACK_TRANSPORT": "native-rpc",
            "FORT_GYM_DFHACK_COMPLETE_DIG": "0",
            "ARTIFACTS_DIR": str(OUTPUT / "unused-artifacts"),
            "FORT_GYM_DB_PATH": str(OUTPUT / "unused-registry.sqlite"),
        }
        publish(OUTPUT / "loaded-boundary.json", loaded)
        with (OUTPUT / "inspection-worker.log").open("xb") as log:
            run_worker(
                [sys.executable, str(Path(__file__)), "inspect", str(runtime)],
                env=worker_env,
                stdout=log,
                timeout=240,
            )
        return read(OUTPUT / "inspection.json")

    try:
        native = run_isolated(
            source=Path("/opt/dwarf-fortress"),
            snapshot=CHECKPOINT,
            digest=FILE_SHA,
            source_kind="campaign_checkpoint",
            output=OUTPUT / "native",
            port=PORT,
            revision=REVISION,
            work=work,
            hook_source=PROJECT / "hook",
            minimum_free_bytes=1073741824,
            checkpoint_copies=0,
            screen_size=(120, 40),
        )
        assert native["native_load_verified"] is True and native["cleanup_verified"] is True
        assert native["experiment"]["passed"] is True
        source()
        result.update(
            status="passed",
            native_load_verified=True,
            native_cleanup_verified=True,
            original_checkpoint_unchanged=True,
        )
    except BaseException as error:
        result.update(error_type=type(error).__name__, error=str(error))
        raise
    finally:
        result["resource_after"] = capture_resources()
        publish(OUTPUT / "result.json", result)
        print(json.dumps(result, allow_nan=False), flush=True)


if __name__ == "__main__":
    with termination_as_interrupt():
        if sys.argv[1:] == ["run"]:
            run()
        elif len(sys.argv) == 3 and sys.argv[1] == "inspect":
            verify_source(REVISION)
            inspect(Path(sys.argv[2]))
        else:
            raise SystemExit("Expected run or inspect RUNTIME")
