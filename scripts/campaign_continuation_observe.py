"""Observe one existing saved-game continuation without model or game calls."""

import argparse
import json
import subprocess
import time
from pathlib import Path

from fort_gym.bench.agent.keyboard_exchange import read
from fort_gym.bench.api import keyboard_continuation_live as live
from fort_gym.bench.run.campaign_checkpoint import verify_checkpoint
from fort_gym.bench.run.campaign_loop import reconciled_usage
from scripts.campaign_keyboard_observe import file_sha, owner_identity
from scripts.campaign_matched_observe import publish_status, snapshot


def baseline(run_dir: Path, operator: Path, checkpoint: Path, index: int) -> tuple[dict, str, str]:
    launch = read(run_dir / "launch.json")
    identity, binding = launch["campaign_id"], launch["binding"]
    row, source, window, readiness = live.source_record(identity)
    if (
        type(index) is not int
        or not 0 <= index < len(readiness["inputs"])
        or readiness["inputs"][index]["campaign_id"] != identity
    ):
        raise ValueError("Owner index differs from the declared continuation order")
    manifest = verify_checkpoint(checkpoint)
    state = read(checkpoint / "agent.json")
    expected = live.identity_fields(identity)
    if (
        launch["run_id"] != run_dir.name
        or binding["operator_sha256"] != file_sha(operator)
        or launch["source_revision"] != expected["source_revision"]
        or launch["image_id"] != row["result"]["execution"]["image_id"]
        or launch["model"] != expected["model"]
        or launch["reasoning_effort"] != "medium"
        or binding["source_revision"] != launch["source_revision"]
        or binding["image_id"] != launch["image_id"]
        or binding["initial_execution_sha256"] != expected["execution_binding_sha256"]
        or binding["declaration_revision"] != expected["declaration_revision"]
        or binding["window_sha256"] != expected["window_sha256"]
        or binding["condition_sha256"] != row["result"]["execution"]["condition_file_sha256"]
        or file_sha(run_dir / "config/window.json") != expected["window_sha256"]
        or binding["prior_checkpoint_sha256"] != manifest["sha256"]
        or manifest["sha256"] != expected["prior_checkpoint_sha256"]
        or manifest["payload"]["campaign_id"] != identity
        or manifest["payload"]["next_step"] != source["cursor"]
        or binding["maximum_new_responses"] != window["steps_per_segment"]
        or binding["data_disk_gib"] != 32
    ):
        raise ValueError("Owner does not bind this exact saved continuation")
    for name in ("agent", "trace", "usage"):
        suffix = ".json" if name == "agent" else ".jsonl"
        if binding["prior_" + name + "_sha256"] != file_sha(checkpoint / (name + suffix)):
            raise ValueError("Stored checkpoint input changed")
    if (
        reconciled_usage(state, (checkpoint / "usage.jsonl").read_bytes()) != state["usage"]
        or state["usage"]["accounted_responses"] != source["cursor"]
        or state["usage"]["total_tokens"] != source["returned_tokens"]
        or not isinstance(state["memory"], str)
    ):
        raise ValueError("Prior memory or cumulative usage is unsettled")
    for key, field in (
        ("initial_cohort_audits", "terminal_audit_sha256"),
        ("cohort_windows_sha256", "declaration_sha256"),
    ):
        if binding[key] != {r["campaign_id"]: r[field] for r in readiness["inputs"]}:
            raise ValueError("Owner does not bind the complete six-input packet")
    suffix = (
        f" -u {operator.name} {index} {binding['declaration_revision']} {binding['declaration_ci']}"
    )
    return {"schema_version": live.SCHEMA, **expected}, state["memory"], suffix


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("run-dir", "operator", "checkpoint", "public-dir"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--owner-pid", type=int, required=True)
    parser.add_argument("--index", type=int, choices=range(6), required=True)
    args = parser.parse_args()
    if args.owner_pid <= 1:
        raise ValueError("A specific existing owner is required")
    base, memory, suffix = baseline(args.run_dir, args.operator, args.checkpoint, args.index)
    original = owner_identity(args.owner_pid)
    if original is None or not original.endswith(suffix):
        raise ValueError("The bound continuation owner is not active")
    while True:
        alive = None
        try:
            alive = owner_identity(args.owner_pid) == original
            value = snapshot(
                args.run_dir,
                base,
                alive=alive,
                now=int(time.time()),
                initial_memory=memory,
                allow_initial_feedback=True,
                projector=live.project_status,
            )
            publish_status(
                args.public_dir, value, projector=live.project_status, filename=live.FILENAME
            )
            print(
                json.dumps({"controller_alive": alive, "new_responses": value["responses"]}),
                flush=True,
            )
            if not alive:
                return
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            RuntimeError,
            subprocess.SubprocessError,
        ) as error:
            print(json.dumps({"observation_error": type(error).__name__}), flush=True)
            if alive is False:
                return
        time.sleep(10)


if __name__ == "__main__":
    main()
