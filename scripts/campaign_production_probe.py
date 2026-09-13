"""Collect bounded native observer evidence inside a caller-owned isolated Linux runtime.

No VM provisioning, model calls, keyboard input, saves or production attribution.
An explicit optional fixture queues one normal brewing job in a declared Still.
The outer runtime owner must admit this fixture only after any active
campaign releases its runtime. A successful probe is not production acceptance.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

from fort_gym.bench.production_brew_evidence import summarize_brew_evidence
from fort_gym.bench.production_brew_fixture import (
    queue_brew,
    validate_brew_receipt,
    validate_workshop_id,
)
from fort_gym.bench.production_observer_probe import (
    ProductionObserverProbe,
    validate_boundary,
)
from scripts.campaign_keyboard_native import file_digest, verify_source
from scripts.campaign_load_smoke import run_isolated, verify_load_source
from scripts.campaign_process import run_worker, termination_as_interrupt
from scripts.campaign_segment import write_result

SCHEMA = "fortgym.native-production-observer-probe/v1"


def validate_limits(intervals: int, ticks: int) -> None:
    if type(intervals) is not int or not 1 <= intervals <= 32:
        raise ValueError("Probe intervals must be between 1 and 32")
    if type(ticks) is not int or not 1 <= ticks <= 2000:
        raise ValueError("Probe ticks per interval must be between 1 and 2000")


def worker(args: argparse.Namespace) -> dict:
    from fort_gym.bench import dfhack_exec
    from fort_gym.bench.env.native_key_catalog import NATIVE_PROFILE
    from fort_gym.bench.run.campaign_environment import NativeCampaignEnvironment

    validate_limits(args.intervals, args.ticks)
    validate_workshop_id(args.brew_workshop_id)
    runtime, output = args.runtime.resolve(), args.output.resolve()
    if (
        runtime != output.parent / "isolated" / "runtime"
        or os.environ.get("DFROOT") != str(runtime)
        or os.environ.get("DFHACK_HOST") != "127.0.0.1"
        or os.environ.get("FORT_GYM_DFHACK_TRANSPORT") != "native-rpc"
    ):
        raise ValueError("Probe worker requires its caller-owned local copied runtime")

    def forbidden_cli(*unused, **kwargs):
        raise AssertionError("Observer probe attempted CLI fallback")

    dfhack_exec.run_dfhack = forbidden_cli
    output.mkdir(mode=0o700, exist_ok=False)
    observer = ProductionObserverProbe(runtime, uuid.uuid4().hex)
    environment = None
    attempted_start = False
    result = {
        "schema_version": SCHEMA,
        "status": "failed",
        "owner": observer.owner,
        "mode": "controlled_brew"
        if args.brew_workshop_id is not None
        else "passive_native_interval",
        "brew_workshop_id": args.brew_workshop_id,
        "brew_queue_attempted": False,
        "brew_queue_confirmed": False,
        "model_calls": 0,
        "gameplay_keys": 0,
        "workshop_jobs_queued": 0,
        "saves_created": 0,
        "intervals_declared": args.intervals,
        "ticks_per_interval": args.ticks,
        "ticks_requested": 0,
        "ticks_advanced": 0,
        "intervals_completed": 0,
        "production_coverage": "inconclusive",
        "independent_production_oracle": False,
        "flow_attribution": "not_measured",
        "native_coverage_validated": False,
        "observer_stopped": False,
        "artifacts": {},
    }

    def retain(name: str, value: dict) -> None:
        path = output / name
        write_result(path, value)
        result["artifacts"][name] = file_digest(path)

    def capture(index: int, state: dict) -> dict:
        value = observer.command("capture")
        retain(
            f"boundary-{index:02}.json", value
        )  # Preserve incomplete reads before validation.
        validate_boundary(value, state, runtime, observer.owner)
        return value

    try:
        environment = NativeCampaignEnvironment(
            expected_dfroot=runtime,
            control_profile=NATIVE_PROFILE,
        )
        state = environment.observe()
        attempted_start = True  # Even an RPC timeout may have installed the observer.
        started = observer.command("start")
        retain("start.json", started)
        if started.get("installed") is not True:
            raise ValueError("Observer installation not confirmed")
        baseline = capture(0, state)
        queued = None
        if args.brew_workshop_id is not None:
            result["brew_queue_attempted"] = True
            # A timeout or malformed reply can follow a real insertion. Never
            # report zero, retry the command, or remove potentially queued jobs.
            result["workshop_jobs_queued"] = None
            reply = queue_brew(observer, state, args.brew_workshop_id)
            retain("brew-queue-response.json", {"raw_response": reply})
            queued = json.loads(reply)
            retain("brew-queue.json", queued)
            if not isinstance(queued, dict):
                raise ValueError("Native brewing receipt is not an object")
            validate_brew_receipt(queued, observer, state, args.brew_workshop_id)
            result["workshop_jobs_queued"] = 1
            result["brew_queue_confirmed"] = True
        for index in range(1, args.intervals + 1):
            result["ticks_requested"] += args.ticks
            after, receipt = environment.advance(args.ticks, state)
            before_clock = {
                key: state[key] for key in ("year", "year_tick", "pause_state")
            }
            after_clock = {key: after[key] for key in before_clock}
            retain(
                f"advance-{index:02}.json",
                {
                    "before": before_clock,
                    "after": after_clock,
                    "receipt": receipt,
                },
            )
            actual = (
                (after["year"] - state["year"]) * 403200
                + after["year_tick"]
                - state["year_tick"]
            )
            if not 0 <= actual <= args.ticks or receipt.get("ticks_advanced") != actual:
                raise ValueError("Native interval receipt and calendar disagree")
            result["ticks_advanced"] += actual
            observed = capture(index, after)
            if queued is not None:
                retain(
                    f"brew-evidence-{index:02}.json",
                    summarize_brew_evidence(queued, baseline, observed),
                )
            if receipt.get("ok") is not True or actual != args.ticks:
                result.update(
                    status="interrupted", stop_reason="native_interval_incomplete"
                )
                break  # Never dismiss menus, retry timeouts, or rescue gameplay.
            result["intervals_completed"] += 1
            state = after
        else:
            result["status"] = "completed"
    except BaseException as error:
        result.update(error_type=type(error).__name__, error=str(error))
        raise
    finally:
        try:
            if attempted_start:
                try:
                    stopped = observer.command("stop")
                    retain("stop.json", stopped)
                    result["observer_stopped"] = stopped.get("installed") is False
                    if not result["observer_stopped"]:
                        raise ValueError("Observer stop not confirmed")
                except BaseException as error:
                    result.update(
                        status="failed",
                        stop_error_type=type(error).__name__,
                        stop_error=str(error),
                    )
                    raise
        finally:
            try:
                if environment is not None:
                    environment.close()
            except BaseException as error:
                result.update(
                    status="failed",
                    close_error_type=type(error).__name__,
                    close_error=str(error),
                )
                raise
            finally:
                write_result(output / "result.json", result)
    return result


def run(args: argparse.Namespace) -> dict:
    validate_limits(args.intervals, args.ticks)
    validate_workshop_id(args.brew_workshop_id)
    if sys.platform != "linux":
        raise ValueError("Run the probe inside the admitted isolated Linux runtime")
    for retained in (args.source, args.checkpoint):
        if (
            args.output.resolve() == retained.resolve()
            or retained.resolve() in args.output.resolve().parents
        ):
            raise ValueError(
                "Probe output must be outside retained source and checkpoint"
            )
    verify_source(args.revision)
    original = file_digest(args.checkpoint / "checkpoint.json")
    verify_load_source(args.checkpoint, original, "campaign_checkpoint")
    args.output.mkdir(mode=0o700, exist_ok=False)
    result = {
        "schema_version": SCHEMA,
        "status": "failed",
        "source_revision": args.revision,
        "source_checkpoint_file_sha256": original,
        "model_calls": 0,
        "brew_workshop_id": args.brew_workshop_id,
        "production_coverage": "inconclusive",
        "native_coverage_validated": False,
        "original_checkpoint_unchanged": False,
        "cleanup_verified": False,
        "outer_runtime_owned_by_caller": True,
    }

    def collect(runtime, environment, loaded):
        child_env = {
            **environment,
            "FORT_GYM_DISABLE_DOTENV": "1",
            "DFROOT": str(runtime),
            "DFHACK_ENABLED": "1",
            "DF_PROTO_ENABLED": "1",
            "DFHACK_HOST": "127.0.0.1",
            "DFHACK_PORT": str(args.port),
            "FORT_GYM_DFHACK_TRANSPORT": "native-rpc",
            "FORT_GYM_DFHACK_COMPLETE_DIG": "0",
            "ARTIFACTS_DIR": str(args.output / "unused-artifacts"),
            "FORT_GYM_DB_PATH": str(args.output / "unused-registry.sqlite"),
        }
        with (args.output / "worker.log").open("xb") as log:
            run_worker(
                [
                    sys.executable,
                    "-m",
                    "scripts.campaign_production_probe",
                    "worker",
                    "--runtime",
                    str(runtime),
                    "--output",
                    str(args.output / "probe"),
                    "--intervals",
                    str(args.intervals),
                    "--ticks",
                    str(args.ticks),
                ]
                + (
                    ["--brew-workshop-id", str(args.brew_workshop_id)]
                    if args.brew_workshop_id is not None
                    else []
                ),
                env=child_env,
                stdout=log,
                timeout=600,
            )
        return json.loads((args.output / "probe/result.json").read_text())

    try:
        isolated = run_isolated(
            source=args.source,
            snapshot=args.checkpoint,
            digest=original,
            source_kind="campaign_checkpoint",
            output=args.output / "isolated",
            port=args.port,
            revision=args.revision,
            work=collect,
            hook_source=Path(__file__).resolve().parents[1] / "hook",
            minimum_free_bytes=1073741824,
            screen_size=(120, 40),
        )
        result.update(
            status=isolated["experiment"]["status"],
            cleanup_verified=isolated["cleanup_verified"],
        )
        if result["cleanup_verified"] is not True:
            raise ValueError("Isolated native process cleanup was not verified")
    except BaseException as error:
        result.update(
            status="failed", error_type=type(error).__name__, error=str(error)
        )
        raise
    finally:
        try:
            verify_load_source(args.checkpoint, original, "campaign_checkpoint")
            result["original_checkpoint_unchanged"] = True
            for name in ("isolated/result.json", "probe/result.json"):
                path = args.output / name
                if path.is_file():
                    result[name + "_sha256"] = file_digest(path)
                    if name == "isolated/result.json":
                        result["cleanup_verified"] = (
                            json.loads(path.read_text()).get("cleanup_verified") is True
                        )
        except BaseException as error:
            result.update(status="failed", source_verification_error=str(error))
            raise
        finally:
            write_result(args.output / "result.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    native = commands.add_parser("run")
    native.add_argument("--source", type=Path, required=True)
    native.add_argument("--checkpoint", type=Path, required=True)
    native.add_argument("--revision", required=True)
    native.add_argument("--port", type=int, default=5610)
    child = commands.add_parser("worker")
    child.add_argument("--runtime", type=Path, required=True)
    for command in (native, child):
        command.add_argument("--output", type=Path, required=True)
        command.add_argument("--intervals", type=int, default=4)
        command.add_argument("--ticks", type=int, default=250)
        command.add_argument("--brew-workshop-id", type=int)
    args = parser.parse_args()
    with termination_as_interrupt():
        result = run(args) if args.command == "run" else worker(args)
    print(
        json.dumps(
            {
                key: result[key]
                for key in ("schema_version", "status", "production_coverage")
            }
        )
    )


if __name__ == "__main__":
    main()
