"""Provider-free acceptance through the committed native environment adapter."""

# ruff: noqa: E402 -- Select the frozen native checkout before package imports.

import hashlib
import json
from pathlib import Path
import sys
import time

PROJECT = Path("/opt/fort-gym-campaign")
sys.path.insert(0, str(PROJECT))

from fort_gym.bench.agent.keyboard_exchange import publish, read
from fort_gym.bench.env.display_key_catalog import BINDING_PROFILE, BINDINGS_SHA256, binding_event
from fort_gym.bench.env.campaign_binding_keys import read_binding_index
from fort_gym.bench.env.screen_observation import text_screen
from fort_gym.bench.run.campaign_checkpoint import verify_checkpoint
from scripts.campaign_keyboard_native import verify_source
from scripts.campaign_load_smoke import run_isolated
from scripts.campaign_process import run_worker, termination_as_interrupt

REVISION = "8b9fffa1de4f93506cbcbdf82fd154aeb17b5697"
CHECKPOINT = Path("/previous-evidence/astra/segment-1/checkpoint")
MANIFEST_SHA = "3225df254ea574ba8d477b6f166112a8defd4ae383a68cade433eac37e078342"
FILE_SHA = "538dc180db6f9c79b15a1cae5cf52f046777e13e861cdfab0738551927cab8fd"
OUTPUT = Path("/evidence/keyboard-binding-integration")
PORT = 5601


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_original():
    manifest = verify_checkpoint(CHECKPOINT)
    assert manifest["sha256"] == MANIFEST_SHA
    assert sha(CHECKPOINT / "checkpoint.json") == FILE_SHA
    assert manifest["payload"]["next_step"] == 256
    assert manifest["payload"]["campaign_id"] == "matched-20260910-astra-r1"
    return manifest


def inspect(runtime):
    from fort_gym.bench.dfhack_exec import run_lua_file
    from fort_gym.bench.run.campaign_environment import NativeCampaignEnvironment

    original = verify_original()
    index = read_binding_index(runtime)
    env = NativeCampaignEnvironment(expected_dfroot=runtime, control_profile=BINDING_PROFILE)
    result = {"status": "failed", "actions": [], "captures": {}, "control_profile": BINDING_PROFILE}

    def scan(mode="inspect"):
        value = run_lua_file("/launch/menu_probe.lua", mode, timeout=10)
        assert value["dfhack_version"] == "0.47.05-r8"
        assert (value["year"], value["year_tick"], value["paused"]) == (30, 152201, True)
        return value

    def capture(name):
        time.sleep(0.15)
        value = {"native": scan(), "screen": text_screen(env.screen_capture())}
        assert (value["screen"]["width"], value["screen"]["height"]) == (120, 40)
        result["captures"][name] = value
        publish(OUTPUT / (name + ".json"), value)
        return value

    def press(keys, name):
        state = env.observe()
        execution = env.apply(
            {"type": "KEYSTROKE", "params": {"keys": keys}, "advance_ticks": 0}, state
        )
        action = {"name": name, "keys": keys, "execution": execution}
        result["actions"].append(action)
        publish(OUTPUT / ("action-" + name + ".json"), action)
        assert execution["accepted"] is True, execution
        receipt = execution["result"]
        assert receipt["control_profile"] == BINDING_PROFILE
        assert receipt["bindings_sha256"] == BINDINGS_SHA256
        assert receipt["keys_sent"] == receipt["keys_confirmed"] == len(keys)
        assert len(receipt["native_receipts"]) == len(keys)
        for key, row in zip(keys, receipt["native_receipts"]):
            assert row["key"] == key
            assert row["events"] == list(index.resolve(binding_event(key)))
            assert row["receipt"]["ok"] and row["receipt"]["input_calls"] == 1
            assert row["receipt"]["events"] == row["events"]
        assert read_binding_index(runtime).sha256 == BINDINGS_SHA256
        return capture(name)

    def query(value):
        assert "/QueryBuilding/" in value["native"]["focus"], value["native"]["focus"]

    def visible(value, text):
        return any(text in row for row in value["screen"]["rows"])

    try:
        loaded = capture("loaded")
        publish(OUTPUT / "operator-reset.json", scan("reset"))
        reset = capture("reset")
        query(press(["q"], "query-enter"))
        escaped = press(["SYM:0:ESC"], "query-exit")
        assert escaped["native"]["focus"] == reset["native"]["focus"]
        query(press(["q"], "query-reenter"))
        publish(OUTPUT / "operator-select.json", scan("select"))
        selected = capture("selected")
        assert selected["native"]["selected_building_id"] == selected["native"]["target"]["id"]
        pos = selected["native"]["cursor"]
        left = press(["SYM:0:Left"], "cursor-left")
        assert left["native"]["cursor"] == {**pos, "x": pos["x"] - 1}
        right = press(["SYM:0:Right"], "cursor-right")
        assert right["native"]["cursor"] == pos
        assert "/AddJob" in press(["a"], "add-open")["native"]["focus"]
        closed = press(["SYM:0:ESC"], "add-exit")
        query(closed)
        assert "/AddJob" not in closed["native"]["focus"]
        assert "/AddJob" in press(["a"], "add-reopen")["native"]["focus"]
        bed = press(["b"], "queue-bed")
        prior_jobs = loaded["native"]["jobs"]
        prior_ids = {job["id"] for job in prior_jobs}
        assert [job for job in bed["native"]["jobs"] if job["id"] in prior_ids] == prior_jobs
        added = [job for job in bed["native"]["jobs"] if job["id"] not in prior_ids]
        assert len(added) == 1 and added[0]["type"] == "ConstructBed"
        assert added[0]["suspend"] is False and added[0]["repeat_job"] is False
        press(["SYM:2:n"], "name-open")
        typed = press(list("FgAb7"), "name-type")
        assert visible(typed, "FgAb7"), "Typed mixed-case text is not visible"
        edited = press(["SYM:0:Backspace"], "name-backspace")
        assert visible(edited, "FgAb") and not visible(edited, "FgAb7")
        confirmed = press(["SYM:0:Enter"], "name-enter")
        assert visible(confirmed, "FgAb"), "Confirmed text is not visible"
        if confirmed["native"]["target"]["name_available"]:
            assert confirmed["native"]["target"]["name"].endswith("FgAb")
        exited = press(["SYM:0:ESC"], "final-exit")
        assert exited["native"]["focus"] == reset["native"]["focus"]
        assert exited["native"]["jobs"] == bed["native"]["jobs"]
        assert verify_original() == original
        result.update(
            status="passed",
            original_checkpoint_unchanged=True,
            binding_file_unchanged=True,
            observed_elapsed_ticks=0,
            new_jobs=added,
        )
    except BaseException as error:
        result.update(error_type=type(error).__name__, error=str(error))
        raise
    finally:
        publish(OUTPUT / "inspection.json", result)
        env.close()
    return result


def run():
    verify_source(REVISION)
    original = verify_original()
    OUTPUT.mkdir(mode=0o700)
    result = {
        "schema_version": "fortgym.private-binding-integration/v1",
        "status": "failed",
        "source_revision": REVISION,
        "checkpoint_sha256": MANIFEST_SHA,
        "driver_sha256": sha(Path(__file__)),
        "probe_sha256": sha(Path("/launch/menu_probe.lua")),
        "model_calls": 0,
        "cloud_vms_created": 0,
        "native_saves_requested": 0,
        "autonomous_gameplay": False,
        "operator_ui_setup": True,
        "human_edited_copy_eligible_for_campaign": False,
        "gameplay_ticks_requested": 0,
    }
    publish(OUTPUT / "launch.json", result)
    try:

        def work(runtime, environment, loaded):
            publish(OUTPUT / "loaded-boundary.json", loaded)
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
            with (OUTPUT / "worker.log").open("xb") as log:
                run_worker(
                    [sys.executable, str(Path(__file__)), "inspect", str(runtime)],
                    env=worker_env,
                    stdout=log,
                    timeout=240,
                )
            return read(OUTPUT / "inspection.json")

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
        assert native["native_load_verified"] and native["cleanup_verified"]
        assert native["experiment"]["status"] == "passed" and verify_original() == original
        result.update(
            status="passed",
            native_load_verified=True,
            cleanup_verified=True,
            original_checkpoint_unchanged=True,
            experiment=native["experiment"],
        )
    except BaseException as error:
        result.update(error_type=type(error).__name__, error=str(error))
        raise
    finally:
        publish(OUTPUT / "result.json", result)
        print(json.dumps({"status": result["status"], "error": result.get("error")}), flush=True)


if __name__ == "__main__":
    with termination_as_interrupt():
        if sys.argv[1:] == ["run"]:
            run()
        elif len(sys.argv) == 3 and sys.argv[1] == "inspect":
            verify_source(REVISION)
            inspect(Path(sys.argv[2]))
        else:
            raise SystemExit("Expected run or inspect RUNTIME")
