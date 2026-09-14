"""Start a new model-selected keyboard campaign from one verified native snapshot.

This owns one copied game process, not VM provisioning or the host model courier.
The caller must provide the credential-free exchange and enforce resource/spend
bounds. No model is silently replaced and no old campaign state is reset.
"""

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

from fort_gym.bench.agent.keyboard_exchange import publish, read
from fort_gym.bench.run.campaign_resources import capture_resources
from fort_gym.bench.run.keyboard_trial_config import load_trial
from scripts.campaign_keyboard_native import PROJECT, MINIMUM_FREE_BYTES, verify_source, worker
from scripts.campaign_load_smoke import run_isolated, verify_snapshot
from scripts.campaign_process import run_worker, termination_as_interrupt


def run_trial(args) -> dict:
    condition, trial = load_trial(args.condition, args.trial)
    if not isinstance(args.campaign_id, str) or not re.fullmatch(
        r"[a-z0-9][a-z0-9_-]{0,99}", args.campaign_id
    ):
        raise ValueError("Fresh trial needs a literal campaign identity")
    if type(args.port) is not int or not 1024 <= args.port <= 65535 or args.port == 5000:
        raise ValueError("Fresh trial needs a dedicated unprivileged game port")
    receipt = trial["source_snapshot_receipt_sha256"]
    verify_snapshot(args.snapshot, receipt)
    for retained in (args.source, args.snapshot):
        if (
            args.output.resolve() == retained.resolve()
            or retained.resolve() in args.output.resolve().parents
        ):
            raise ValueError("Fresh trial output must be outside retained source and snapshot")
    args.output.mkdir(mode=0o700, exist_ok=False)
    exchange = args.output / "exchange"
    exchange.mkdir(mode=0o700)
    publish(args.output / "condition.json", condition)
    publish(args.output / "trial.json", trial)
    result = {
        "schema_version": "fortgym.keyboard-fresh-trial-result/v1",
        "campaign_id": args.campaign_id,
        "source_revision": args.revision,
        "source_snapshot_receipt_sha256": receipt,
        "status": "failed",
        "native_load_verified": False,
        "runtime_cleanup_verified": False,
        "source_snapshot_unchanged": False,
        "new_checkpoint_verified": False,
    }

    def resources(stage):
        if trial.get("resource_observation_profile") is not None:
            result.setdefault("resource_observations", []).append(
                {"stage": stage, **capture_resources()}
            )

    def play(runtime, environment, loaded):
        loaded_path = args.output / "loaded-boundary.json"
        publish(loaded_path, loaded)
        worker_env = {
            **environment,
            "FORT_GYM_DISABLE_DOTENV": "1",
            "DFROOT": str(runtime),
            "DFHACK_ENABLED": "1",
            "DF_PROTO_ENABLED": "1",
            "DFHACK_HOST": "127.0.0.1",
            "DFHACK_PORT": str(args.port),
            "FORT_GYM_DFHACK_TRANSPORT": trial["runtime_rpc_transport"],
            "FORT_GYM_DFHACK_COMPLETE_DIG": "0",
            "ARTIFACTS_DIR": str(args.output / "unused-artifacts"),
            "FORT_GYM_DB_PATH": str(args.output / "unused-registry.sqlite"),
        }
        command = [
            sys.executable,
            "-m",
            "scripts.campaign_keyboard_trial",
            "worker",
            "--condition",
            str(args.condition),
            "--trial",
            str(args.trial),
            "--campaign-id",
            args.campaign_id,
            "--revision",
            args.revision,
            "--output",
            str(args.output / "segment-0"),
            "--runtime",
            str(runtime),
            "--exchange",
            str(exchange),
            "--loaded-boundary",
            str(loaded_path),
        ]
        with (args.output / "worker-0.log").open("xb") as log:
            resources("loaded-before-worker")
            try:
                run_worker(
                    command,
                    env=worker_env,
                    stdout=log,
                    timeout=trial["steps_per_segment"]
                    * (condition["exchange_timeout_seconds"] + 120)
                    + 300,
                )
            except subprocess.CalledProcessError:
                failed = read(args.output / "segment-0/result.json")
                if (
                    failed.get("campaign_id") != args.campaign_id
                    or failed.get("source_revision") != args.revision
                    or failed.get("status") not in ("failed", "checkpoint_failed")
                ):
                    raise
                return failed
            finally:
                resources("after-worker")
        return read(args.output / "segment-0/result.json")

    try:
        resources("before-runtime")
        native = run_isolated(
            source=args.source,
            snapshot=args.snapshot,
            digest=receipt,
            output=args.output / "runtime-0",
            port=args.port,
            revision=args.revision,
            work=play,
            hook_source=PROJECT / "hook",
            source_kind="native_snapshot",
            minimum_free_bytes=MINIMUM_FREE_BYTES,
            checkpoint_copies=1,
            screen_size=tuple(condition["screen_size"]),
        )
        result["native_load_verified"] = native["native_load_verified"]
        result["runtime_cleanup_verified"] = native["cleanup_verified"]
        result["segment"] = segment = native["experiment"]
        if (
            native["native_load_verified"] is not True
            or native["cleanup_verified"] is not True
            or segment["campaign_id"] != args.campaign_id
            or segment["source_revision"] != args.revision
        ):
            raise ValueError("Fresh trial runtime or campaign identity differs")
        if (
            segment["status"] == "bounded_segment_complete"
            and segment["checkpoint_verified"] is True
        ):
            result.update(
                status="completed" if segment["stop_reason"] == "segment_limit" else "paused",
                new_checkpoint_verified=True,
            )
        elif (
            segment["status"] == "budget_limited_pause"
            and segment.get("initial_snapshot_only") is True
        ):
            result["status"] = "budget_limited_pause"
    except Exception as error:
        result.update(error_type=type(error).__name__, error=str(error))
    finally:
        resources("after-runtime-unwind")
        try:
            verify_snapshot(args.snapshot, receipt)
            result["source_snapshot_unchanged"] = True
        except (OSError, ValueError, RuntimeError):
            result["status"] = "failed"
        publish(args.output / "result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "worker"):
        command = commands.add_parser(name)
        for key in ("condition", "trial", "output"):
            command.add_argument("--" + key, type=Path, required=True)
        command.add_argument("--campaign-id", required=True)
        command.add_argument("--revision", required=True)
        if name == "run":
            for key in ("source", "snapshot"):
                command.add_argument("--" + key, type=Path, required=True)
            command.add_argument("--port", type=int, required=True)
        else:
            for key in ("runtime", "exchange", "loaded-boundary"):
                command.add_argument("--" + key, type=Path, required=True)
    args = parser.parse_args()
    for key, value in vars(args).items():
        if isinstance(value, Path):
            setattr(args, key, value.resolve())
    verify_source(args.revision)
    with termination_as_interrupt():
        result = run_trial(args) if args.command == "run" else worker(args)
    print(json.dumps(result), flush=True)
    if result["status"] not in (
        "completed",
        "paused",
        "bounded_segment_complete",
        "budget_limited_pause",
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
