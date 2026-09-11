"""Read-only independent review; invoke from the declared implementation checkout."""

import hashlib
import json
from pathlib import Path
import sys

from fort_gym.bench.env.campaign_binding_keys import read_binding_index
from fort_gym.bench.env.display_key_catalog import BINDING_PROFILE, BINDINGS_SHA256, binding_event
from fort_gym.bench.env.screen_observation import expand_text_screen, text_screen
from fort_gym.bench.run.campaign_checkpoint import verify_checkpoint


REVISION = "8b9fffa1de4f93506cbcbdf82fd154aeb17b5697"


def read(path):
    return json.loads(path.read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def boundary(value):
    assert type(value["year"]) is type(value["year_tick"]) is int
    assert (value["year"], value["year_tick"], value["paused"]) == (30, 152201, True)


def review(base, source):
    out = base / "attempt"
    evidence = out / "evidence/keyboard-binding-integration"
    owner, result = read(out / "result.json"), read(evidence / "result.json")
    native = read(evidence / "native/result.json")
    inspection = read(evidence / "inspection.json")
    assert owner["status"] == result["status"] == inspection["status"] == "passed"
    assert owner["source_revision"] == result["source_revision"] == REVISION
    assert result["experiment"] == native["experiment"] == inspection
    assert (
        native["native_load_verified"] and native["cleanup_verified"] and native["listener_closed"]
    )
    assert native["remaining_live_processes"] == [] and native["port"] == 5601
    boundary(native["loaded"])
    assert owner["operator_sha256"] == sha(base / "operator.py")
    assert owner["context_sha256"] == {
        name: sha(base / name) for name in ("fixture.py", "menu_probe.lua")
    }
    assert owner["build_sha256"] == {
        name: sha(base / "context" / name) for name in ("Dockerfile", "source.bundle")
    }
    assert result["driver_sha256"] == sha(base / "fixture.py")
    assert result["probe_sha256"] == sha(base / "menu_probe.lua")
    manifest = verify_checkpoint(source)
    assert (
        manifest["sha256"]
        == result["checkpoint_sha256"]
        == "3225df254ea574ba8d477b6f166112a8defd4ae383a68cade433eac37e078342"
    )
    assert (
        sha(source / "checkpoint.json")
        == native["source_checkpoint_file_sha256"]
        == "538dc180db6f9c79b15a1cae5cf52f046777e13e861cdfab0738551927cab8fd"
    )
    state = read(out / "container-final-state.log")
    assert (state["Running"], state["Pid"], state["ExitCode"], state["OOMKilled"]) == (
        False,
        0,
        0,
        False,
    )
    config = read(out / "container-config.json")
    assert config["Image"] == owner["image_id"] == read(out / "image-inspect.json")["Id"]
    host = config["HostConfig"]
    assert host["NetworkMode"] == "none" and host["Init"] and host["PidsLimit"] == 256
    assert host["Memory"] == host["MemorySwap"] == 1610612736 and host["NanoCpus"] == 2000000000
    assert host["PortBindings"] == {}
    assert any(
        m["Destination"] == "/previous-evidence" and m["RW"] is False for m in config["Mounts"]
    )
    for name in ("container-stop", "container-log", "container-final-state", "evidence-copy"):
        assert owner[name + "_returncode"] == 0
    assert owner["guest_poweroff_returncode"] == owner["vm_stop_returncode"] == 0
    assert owner["vm_observed_stopped"] and owner["vm_config_unchanged"]
    index = read_binding_index(evidence / "native/runtime")
    assert index.sha256 == BINDINGS_SHA256
    expected = [
        ("query-enter", ["q"]),
        ("query-exit", ["SYM:0:ESC"]),
        ("query-reenter", ["q"]),
        ("cursor-left", ["SYM:0:Left"]),
        ("cursor-right", ["SYM:0:Right"]),
        ("add-open", ["a"]),
        ("add-exit", ["SYM:0:ESC"]),
        ("add-reopen", ["a"]),
        ("queue-bed", ["b"]),
        ("name-open", ["SYM:2:n"]),
        ("name-type", list("FgAb7")),
        ("name-backspace", ["SYM:0:Backspace"]),
        ("name-enter", ["SYM:0:Enter"]),
        ("final-exit", ["SYM:0:ESC"]),
    ]
    assert [(row["name"], row["keys"]) for row in inspection["actions"]] == expected
    for action in inspection["actions"]:
        assert read(evidence / ("action-" + action["name"] + ".json")) == action
        execution = action["execution"]
        receipt = execution["result"]
        assert execution["accepted"] and receipt["control_profile"] == BINDING_PROFILE
        assert receipt["keys_sent"] == receipt["keys_confirmed"] == len(action["keys"])
        assert (
            receipt["command_mutation"] == "completed"
            and receipt["bindings_sha256"] == BINDINGS_SHA256
        )
        assert len(receipt["native_receipts"]) == len(action["keys"])
        for key, row in zip(action["keys"], receipt["native_receipts"]):
            events = list(index.resolve(binding_event(key)))
            assert row["key"] == key and row["events"] == events
            native_receipt = row["receipt"]
            assert native_receipt["schema_version"] == "fortgym.campaign-binding-set/v1"
            assert native_receipt["events"] == events and native_receipt["ok"]
            assert (
                native_receipt["input_calls"] == 1
                and native_receipt["command_mutation"] == "completed"
            )
            boundary(native_receipt["before"])
            boundary(native_receipt["after"])
    captures = inspection["captures"]
    for name, capture in captures.items():
        assert read(evidence / (name + ".json")) == capture
        boundary(capture["native"])
        assert text_screen(expand_text_screen(capture["screen"])) == capture["screen"]

    def focus(name):
        return captures[name]["native"]["focus"]

    assert "/QueryBuilding/" in focus("query-enter") and "/QueryBuilding/" in focus("query-reenter")
    assert focus("reset") == focus("query-exit") == focus("final-exit")
    pos = captures["selected"]["native"]["cursor"]
    assert captures["cursor-left"]["native"]["cursor"] == {**pos, "x": pos["x"] - 1}
    assert captures["cursor-right"]["native"]["cursor"] == pos
    assert "/AddJob" in focus("add-open") and "/AddJob" in focus("add-reopen")
    assert "/QueryBuilding/" in focus("add-exit") and "/AddJob" not in focus("add-exit")
    old_jobs = captures["loaded"]["native"]["jobs"]
    old_ids = {row["id"] for row in old_jobs}
    jobs = captures["queue-bed"]["native"]["jobs"]
    assert [job for job in jobs if job["id"] in old_ids] == old_jobs
    added = [job for job in jobs if job["id"] not in old_ids]
    assert len(added) == 1 and added[0]["type"] == "ConstructBed"
    assert added[0]["suspend"] is False and added[0]["repeat_job"] is False
    assert captures["final-exit"]["native"]["jobs"] == jobs
    assert any("FgAb7" in row for row in captures["name-type"]["screen"]["rows"])
    assert any("FgAb" in row for row in captures["name-backspace"]["screen"]["rows"])
    assert not any("FgAb7" in row for row in captures["name-backspace"]["screen"]["rows"])
    assert any("FgAb" in row for row in captures["name-enter"]["screen"]["rows"])
    name = captures["name-enter"]["native"]["target"]
    if name["name_available"]:
        assert name["name"].endswith("FgAb")
    assert inspection["original_checkpoint_unchanged"] and inspection["observed_elapsed_ticks"] == 0
    return {
        "schema_version": "fortgym.private-binding-integration-review/v1",
        "passed": True,
        "source_revision": REVISION,
        "control_profile": BINDING_PROFILE,
        "action_batches": len(expected),
        "key_presses": sum(len(keys) for _, keys in expected),
        "new_jobs": added,
        "native_name_available": name["name_available"],
        "native_name": name.get("name"),
        "model_calls": 0,
        "autonomous_gameplay": False,
        "native_saves_requested": 0,
        "observed_elapsed_ticks": 0,
        "source_checkpoint_unchanged": True,
        "native_cleanup_verified": True,
        "recorded_vm_teardown_verified": True,
        "hardware_energy_and_app_cost_usd": None,
        "owner_sha256": sha(out / "result.json"),
        "native_result_sha256": sha(evidence / "result.json"),
        "inspection_sha256": sha(evidence / "inspection.json"),
        "reviewer_sha256": sha(Path(__file__)),
    }


if __name__ == "__main__":
    assert len(sys.argv) == 3, "Expected immutable attempt directory and source checkpoint"
    print(json.dumps(review(Path(sys.argv[1]), Path(sys.argv[2])), indent=2, allow_nan=False))
