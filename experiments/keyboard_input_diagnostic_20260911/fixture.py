"""Provider-free native input diagnostic; all operator-edited copies are discarded as campaign origins."""

import hashlib
import json
from pathlib import Path
import sys
import time

PROJECT = Path("/opt/fort-gym-campaign")
sys.path.insert(0, str(PROJECT))

from fort_gym.bench.agent.keyboard_exchange import publish, read
from fort_gym.bench.env.screen_observation import text_screen
from fort_gym.bench.run.campaign_checkpoint import verify_checkpoint
from scripts.campaign_keyboard_native import verify_source
from scripts.campaign_load_smoke import run_isolated
from scripts.campaign_process import run_worker, termination_as_interrupt

REVISION = "1bc49b9675b1c82ad502bbd6d8461c9cdbf077e9"
CHECKPOINT = Path("/previous-evidence/astra/segment-1/checkpoint")
MANIFEST_SHA = "3225df254ea574ba8d477b6f166112a8defd4ae383a68cade433eac37e078342"
FILE_SHA = "538dc180db6f9c79b15a1cae5cf52f046777e13e861cdfab0738551927cab8fd"
OUTPUT = Path("/evidence/keyboard-input-diagnostic")
PORTS = {"custom_b": 5589, "literal_b": 5590, "native_bed": 5591, "scroll_select": 5592}
ARMS = {
    "custom_b": ["CUSTOM_B"],
    "literal_b": ["STRING_A098"],
    "native_bed": ["HOTKEY_CARPENTER_BED"],
    "scroll_select": ["STANDARDSCROLL_DOWN", "SELECT"],
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_original():
    manifest = verify_checkpoint(CHECKPOINT)
    assert manifest["sha256"] == MANIFEST_SHA
    assert sha(CHECKPOINT / "checkpoint.json") == FILE_SHA
    assert manifest["payload"]["next_step"] == 256
    assert manifest["payload"]["campaign_id"] == "matched-20260910-astra-r1"
    return manifest


def inspect(runtime, arm):
    from fort_gym.bench.dfhack_exec import run_lua_file
    from fort_gym.bench.run.campaign_environment import NativeCampaignEnvironment

    out = OUTPUT / arm
    source = verify_original()
    env = NativeCampaignEnvironment(expected_dfroot=runtime, control_profile="native_keyboard/v2")
    result = {"arm": arm, "keys": ARMS[arm], "actions": [], "autonomous_gameplay": False}

    def scan(mode="inspect"):
        value = run_lua_file("/launch/menu_probe.lua", mode, timeout=10)
        assert value["dfhack_version"] == "0.47.05-r8"
        assert (value["year"], value["year_tick"], value["paused"]) == (30, 152201, True)
        return value

    def capture(name):
        time.sleep(0.15)  # UI frames only; the world must remain paused.
        value = {"native": scan(), "screen": text_screen(env.screen_capture())}
        assert (value["screen"]["width"], value["screen"]["height"]) == (120, 40)
        publish(out / (name + ".json"), value)
        return value

    def press(keys, phase):
        before = env.observe()
        execution = env.apply({"type": "KEYSTROKE", "params": {"keys": keys}, "advance_ticks": 0}, before)
        row = {"phase": phase, "keys": keys, "execution": execution}
        result["actions"].append(row)
        publish(out / ("action-" + str(len(result["actions"])) + ".json"), row)
        assert execution["accepted"] is True
        assert execution["result"]["keys_confirmed"] == len(keys)
        return capture("after-action-" + str(len(result["actions"])))

    try:
        result["loaded"] = capture("loaded")
        publish(out / "ui-reset.json", scan("reset"))
        press(["D_BUILDJOB"], "operator_menu_setup")
        publish(out / "ui-select.json", scan("select"))
        selected = capture("selected-workshop")
        assert selected["native"]["selected_building_id"] == selected["native"]["target"]["id"]
        before = press(["BUILDJOB_ADD"], "operator_menu_setup")
        assert "/AddJob" in before["native"]["focus"]
        assert before["native"]["jobs"] == result["loaded"]["native"]["jobs"]
        result["before_input"] = before
        result["after_input"] = press(ARMS[arm], "tested_input")
        known_ids = {row["id"] for row in before["native"]["jobs"]}
        result["new_jobs"] = [row for row in result["after_input"]["native"]["jobs"] if row["id"] not in known_ids]
        result["queued_bed"] = any(row["type"] == "ConstructBed" for row in result["new_jobs"])
        result["original_checkpoint_unchanged"] = verify_original() == source
        result["observed_elapsed_ticks"] = 0
        result["status"] = "passed"
        publish(out / "inspection.json", result)
        return result
    finally:
        env.close()


def run():
    verify_source(REVISION)
    original = verify_original()
    OUTPUT.mkdir(mode=0o700)
    summary = {
        "schema_version": "fortgym.private-native-keyboard-diagnostic/v1",
        "status": "failed", "source_revision": REVISION, "checkpoint_sha256": MANIFEST_SHA,
        "driver_sha256": sha(Path(__file__)), "probe_sha256": sha(Path("/launch/menu_probe.lua")),
        "arms": [], "model_calls": 0, "cloud_vms_created": 0,
        "native_saves_requested": 0, "autonomous_gameplay": False,
        "operator_ui_setup": True, "human_edited_copy_eligible_for_campaign": False,
        "gameplay_ticks_requested": 0,
    }
    publish(OUTPUT / "launch.json", summary)
    try:
        for arm in ARMS:
            port = PORTS[arm]
            out = OUTPUT / arm
            out.mkdir(mode=0o700)
            def work(runtime, environment, loaded):
                publish(out / "loaded-boundary.json", loaded)
                worker_env = {
                    **environment, "FORT_GYM_DISABLE_DOTENV": "1", "DFROOT": str(runtime),
                    "DFHACK_ENABLED": "1", "DF_PROTO_ENABLED": "1", "DFHACK_HOST": "127.0.0.1",
                    "DFHACK_PORT": str(port), "FORT_GYM_DFHACK_TRANSPORT": "native-rpc",
                    "FORT_GYM_DFHACK_COMPLETE_DIG": "0",
                    "ARTIFACTS_DIR": str(out / "unused-artifacts"),
                    "FORT_GYM_DB_PATH": str(out / "unused-registry.sqlite"),
                }
                with (out / "worker.log").open("xb") as log:
                    run_worker([sys.executable, str(Path(__file__)), "inspect", str(runtime), arm],
                               env=worker_env, stdout=log, timeout=180)
                return read(out / "inspection.json")
            native = run_isolated(
                source=Path("/opt/dwarf-fortress"), snapshot=CHECKPOINT, digest=FILE_SHA,
                source_kind="campaign_checkpoint", output=out / "native", port=port,
                revision=REVISION, work=work, hook_source=PROJECT / "hook",
                minimum_free_bytes=1073741824, checkpoint_copies=0, screen_size=(120, 40),
            )
            assert native["native_load_verified"] and native["cleanup_verified"]
            summary["arms"].append(native["experiment"])
            publish(out / "completed.json", {"native_load_verified": True, "cleanup_verified": True})
        first = summary["arms"][0]["before_input"]
        for result in summary["arms"]:
            assert result["before_input"]["native"] == first["native"]
            # Full retained screen rows establish the same visible input menu.
            assert result["before_input"]["screen"]["rows"] == first["screen"]["rows"]
        assert verify_original() == original
        summary.update(status="passed", same_menu_and_queue_start=True,
                       original_checkpoint_unchanged=True, observed_elapsed_ticks=0)
    except BaseException as error:
        summary.update(error_type=type(error).__name__, error=str(error))
        raise
    finally:
        publish(OUTPUT / "result.json", summary)
        print(json.dumps({"status": summary["status"], "completed_arms": len(summary["arms"])}), flush=True)


if __name__ == "__main__":
    with termination_as_interrupt():
        if sys.argv[1:] == ["run"]:
            run()
        elif len(sys.argv) == 4 and sys.argv[1] == "inspect" and sys.argv[3] in ARMS:
            verify_source(REVISION)
            inspect(Path(sys.argv[2]), sys.argv[3])
        else:
            raise SystemExit("Expected run or inspect RUNTIME ARM")
