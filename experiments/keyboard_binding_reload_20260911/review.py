"""Independent read-only terminal review; require native and VM teardown evidence."""

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
BASE = (
    ROOT
    / "fort_gym/artifacts/native-local-20260906/runtime-v2/keyboard-matched-pilot-v1/keyboard-bindings-astra-r1-reload-v1"
)
OWNER_SHA = "3499128df685fe47c486b1785b66b3cc1fee457f58560fa6382cce2940e7ec63"


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(path.read_text())


def main():
    assert not (BASE / "terminal-review.json").exists()
    assert sha(BASE / "operator.py") == OWNER_SHA
    spec = importlib.util.spec_from_file_location("reload_owner", BASE / "operator.py")
    owner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(owner)
    sys.path.insert(0, str(owner.WORKTREE))
    from fort_gym.bench.eval.campaign_profile import metrics_from_state
    from fort_gym.bench.run.campaign_loop import _clock, reconciled_usage
    from fort_gym.bench.run.campaign_save import save_inventory

    checkpoint = owner.check_source()
    out, native = owner.OUT, owner.OUT / "evidence/binding-checkpoint32-reload"
    execution, result = read(out / "result.json"), read(native / "result.json")
    inspection, runtime = read(native / "inspection.json"), read(native / "native/result.json")
    preflight = read(BASE / "preflight.json")
    assert execution["status"] == result["status"] == "passed"
    assert execution["native"] == result
    assert (
        execution["source_revision"]
        == result["source_revision"]
        == inspection["source_revision"]
        == runtime["code_revision"]
        == owner.REVISION
    )
    assert execution["image_id"] == preflight["image_id"] == owner.IMAGE
    assert (
        result["driver_sha256"]
        == execution["fixture_sha256"]
        == preflight["fixture_sha256"]
        == owner.FIXTURE_SHA
    )
    assert execution["operator_sha256"] == preflight["operator_sha256"] == OWNER_SHA
    assert execution["preflight_sha256"] == sha(BASE / "preflight.json")
    assert runtime["experiment"] == inspection and inspection["passed"] is True
    assert (
        runtime["native_load_verified"]
        is runtime["cleanup_verified"]
        is runtime["listener_closed"]
        is True
    )
    assert runtime["remaining_live_processes"] == []
    loaded = runtime["loaded"]
    assert (loaded["year"], loaded["year_tick"], loaded["paused"], loaded["save_name"]) == (
        30,
        32301,
        True,
        "campaign-resume",
    )
    assert read(native / "loaded-boundary.json") == loaded
    assert runtime["source_checkpoint_file_sha256"] == sha(owner.CHECKPOINT / "checkpoint.json")
    assert (
        save_inventory(native / "native/runtime/data/save/campaign-resume")
        == checkpoint["payload"]["native_save"]["files"]
    )
    original = read(owner.CHECKPOINT / "agent.json")
    assert read(native / "agent-restored.json") == original
    assert (
        reconciled_usage(original, (native / "restored-loop/usage.jsonl").read_bytes())
        == original["usage"]
        == inspection["usage"]
    )
    for name in ("trace.jsonl", "usage.jsonl"):
        assert (native / "restored-loop" / name).read_bytes() == (
            owner.CHECKPOINT / name
        ).read_bytes()
    assert inspection["next_step"] == 32 and inspection["committed_elapsed_ticks"] == 15500
    assert (
        original["usage"]["accounted_responses"] == 32
        and original["usage"]["total_tokens"] == 785690
    )
    expected = read(owner.PRIOR_OUT / "terminal-review.json")["saved_metrics"]
    before, after = read(native / "native-before.json"), read(native / "native-after.json")
    assert _clock(before) == _clock(after) == 30 * 403200 + 32301
    assert before["pause_state"] is after["pause_state"] is True
    assert (
        metrics_from_state(before)
        == metrics_from_state(after)
        == expected
        == inspection["saved_metrics"]
    )
    assert original["configuration"]["control_profile"] == "native_keyboard_bindings/v1"
    assert original["configuration"]["bindings_sha256"] == inspection["bindings_sha256"]
    screen = read(native / "screen.json")
    assert [screen["width"], screen["height"]] == inspection["actual_screen_size"] == [120, 40]
    for name in ("binding-probe-before.json", "binding-probe-after.json"):
        probe = read(native / name)
        assert probe["accepted"] is True
        value = probe["result"]
        assert value["keys_sent"] == value["keys_confirmed"] == 0
        assert value["command_mutation"] == "not_attempted" and value["native_receipts"] == []
        boundary = value["boundary_probe"]["result"]["native_receipts"]
        assert len(boundary) == 1 and boundary[0]["mode"] == "probe"
        assert boundary[0]["before"] == boundary[0]["after"]
        assert boundary[0]["after"]["focus"] == inspection["loaded_menu_focus"]
    assert (
        inspection["saved_menu_focus"]
        == checkpoint["payload"]["native_save"]["save_operation"]["ui_after"]["focus"]
    )
    assert inspection["menu_focus_equal"] is (
        inspection["saved_menu_focus"] == inspection["loaded_menu_focus"]
    )
    assert (
        inspection["full_menu_equivalence_claimed"]
        is inspection["manual_menu_restoration"]
        is False
    )
    for key in (
        "normal_loop_restore_verified",
        "agent_unchanged",
        "trace_usage_history_unchanged",
        "original_checkpoint_unchanged",
    ):
        assert inspection[key] is True
    for key in (
        "model_calls",
        "gameplay_actions",
        "gameplay_ticks_requested",
        "observed_elapsed_ticks",
        "native_saves_requested",
    ):
        assert inspection[key] == 0
    assert execution["cloud_vms_created"] == 0
    for key in ("container-stop", "container-log", "container-final-state", "evidence-copy"):
        assert execution[key + "_returncode"] == 0
    final = read(out / "container-final-state.log")
    assert (final["Running"], final["Pid"], final["ExitCode"], final["OOMKilled"]) == (
        False,
        0,
        0,
        False,
    )
    config = read(out / "container-config.json")
    host = config["HostConfig"]
    assert host["Init"] is True and host["PidsLimit"] == 256 and host["NetworkMode"] == "none"
    assert host["Memory"] == host["MemorySwap"] == 1610612736 and host["NanoCpus"] == 2000000000
    assert host["PortBindings"] == {} and config["Image"] == owner.IMAGE
    assert any(
        m["Destination"] == "/previous-evidence"
        and m["RW"] is False
        and m["Name"] == owner.PRIOR + "-evidence"
        for m in config["Mounts"]
    )
    assert (
        execution["vm_stop_returncode"] == 0
        and execution["vm_observed_stopped"] is execution["vm_config_unchanged"] is True
    )
    assert owner.stopped()
    source_paths = [
        BASE / "operator.py",
        BASE / "preflight.json",
        owner.FIXTURE,
        Path(__file__),
        out / "result.json",
        out / "container-config.json",
        out / "container-final-state.log",
        native / "result.json",
        native / "inspection.json",
        native / "native/result.json",
        native / "agent-restored.json",
        native / "native-before.json",
        native / "native-after.json",
        native / "screen.json",
        native / "binding-probe-before.json",
        native / "binding-probe-after.json",
        native / "restored-loop/trace.jsonl",
        native / "restored-loop/usage.jsonl",
    ]
    report = {
        "schema_version": "fortgym.private-binding-reload-terminal-review/v1",
        "passed": True,
        "source_revision": owner.REVISION,
        "declaration_revision": preflight["declaration_revision"],
        "image_id": owner.IMAGE,
        "checkpoint_sha256": checkpoint["sha256"],
        "native_load_verified": True,
        "normal_loop_restore_verified": True,
        "source_and_copied_save_files_verified": len(checkpoint["payload"]["native_save"]["files"]),
        "next_step": 32,
        "committed_elapsed_ticks": 15500,
        "usage": original["usage"],
        "saved_metrics": expected,
        "source_checkpoint_unchanged": True,
        "saved_menu_focus": inspection["saved_menu_focus"],
        "loaded_menu_focus": inspection["loaded_menu_focus"],
        "menu_focus_equal": inspection["menu_focus_equal"],
        "full_menu_equivalence_claimed": False,
        "native_cleanup_verified": True,
        "vm_teardown_verified": True,
        "guest_poweroff_returncode": execution["guest_poweroff_returncode"],
        "vm_stop_returncode": 0,
        "vm_live_observed_stopped": True,
        "new_model_calls": 0,
        "new_gameplay_ticks": 0,
        "new_native_saves": 0,
        "additional_autonomous_play": False,
        "sustainability_proven": False,
        "sources": {str(path.relative_to(ROOT)): sha(path) for path in source_paths},
    }
    owner.write(BASE / "terminal-review.json", report)
    print(
        json.dumps(
            {
                "passed": True,
                "next_step": 32,
                "saved_menu_focus": inspection["saved_menu_focus"],
                "loaded_menu_focus": inspection["loaded_menu_focus"],
                "audit_sha256": sha(BASE / "terminal-review.json"),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
