"""Run or resume a bounded model-selected campaign segment in an isolated game.

This is a development condition, separate from the legacy probe and frozen gates.
Provider use requires the existing project credential and applicable authorization.
The outer launcher owns the copied runtime and verifies its teardown on all exits.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.campaign_development import load_config, make_agent
from scripts.campaign_load_smoke import run_isolated


def load_segment_config(path: Path, model: str) -> dict:
    config = load_config(path, model)
    condition = config.get("condition_id")
    if (
        config.get("runner") != "campaign-loop/v1"
        or not isinstance(condition, str)
        or not condition.strip()
        or len(condition) > 128
    ):
        raise ValueError("Campaign segments require their own declared runner condition")
    return config


def write_result(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())


def run_segment(
    *,
    agent,
    environment,
    snapshotter,
    output: Path,
    config: dict,
    campaign_id: str,
    model: str,
    revision: str,
    checkpoint: Path | None = None,
    latest_usage: Path | None = None,
) -> dict:
    """Own one segment's terminal record; never interpret a pause as game collapse."""
    from fort_gym.bench.agent.governed_llm import GovernedBudgetCapError
    from fort_gym.bench.run.campaign_loop import CampaignLoop

    if (checkpoint is None) != (latest_usage is None):
        raise ValueError("Resume requires both checkpoint and latest usage journal")
    result = {
        "schema_version": "fortgym.campaign-segment/v1",
        "condition_id": config["condition_id"],
        "campaign_id": campaign_id,
        "segment_id": output.name,
        "model": model,
        "configuration": config,
        "code_revision": revision,
        "status": "started",
        "segment_committed_steps": 0,
        "checkpoint": str(checkpoint) if checkpoint is not None else None,
        "new_checkpoint_verified": False,
        "year_two_gameplay_verified": False,
    }
    loop = None
    try:
        result["native_start"] = environment.observe()
        if checkpoint is None:
            loop = CampaignLoop(
                campaign_id=campaign_id,
                agent=agent,
                environment=environment,
                output=output / "campaign",
                max_advance_ticks=config["max_advance_ticks"],
            )
        else:
            assert latest_usage is not None
            from fort_gym.bench.run.campaign_checkpoint import verify_checkpoint

            if verify_checkpoint(checkpoint)["payload"]["campaign_id"] != campaign_id:
                raise ValueError("Resume campaign identity differs from the checkpoint")
            loop = CampaignLoop.resume(
                checkpoint,
                agent=agent,
                environment=environment,
                output=output / "campaign",
                latest_usage_path=latest_usage,
            )
        result["first_step"] = loop.next_step
        for _ in range(config["max_steps"]):
            # Stop at the existing boundary when a cap is already reached, without
            # starting a failed decision or mutating the agent's gameplay memory.
            if agent.dispatches >= config["max_dispatches"]:
                raise GovernedBudgetCapError("Campaign dispatch allowance reached")
            agent._pre_dispatch_gate()
            loop.step()
            result["segment_committed_steps"] += 1
        result["status"] = "bounded_segment_complete"
    except GovernedBudgetCapError as error:
        result.update(
            status="budget_limited_pause", error_type=type(error).__name__, error=str(error)
        )
    except Exception as error:
        result.update(status="failed", error_type=type(error).__name__, error=str(error))
    finally:
        result["recovery_requires_reconciliation"] = bool(loop is not None and loop.failed)
        if loop is not None:
            result["next_step"] = loop.next_step
            if loop.at_boundary and result["segment_committed_steps"]:
                try:
                    destination = output / "checkpoint"
                    manifest = loop.checkpoint(
                        destination, snapshotter=snapshotter, code_revision=revision
                    )
                    result.update(
                        checkpoint=str(destination),
                        checkpoint_payload_sha256=manifest["sha256"],
                        checkpoint_file_sha256=hashlib.sha256(
                            (destination / "checkpoint.json").read_bytes()
                        ).hexdigest(),
                        new_checkpoint_verified=True,
                    )
                except Exception as error:
                    result.update(
                        status="checkpoint_failed",
                        checkpoint_error_type=type(error).__name__,
                        checkpoint_error=str(error),
                    )
        try:
            result["native_final"] = environment.observe()
        except Exception as error:
            result["native_final_error"] = type(error).__name__ + ": " + str(error)
        try:
            state = agent.export_campaign_state()
            result["usage"] = state["usage"]
            write_result(output / "agent-final.json", state)
        except Exception as error:
            result["agent_final_error"] = type(error).__name__ + ": " + str(error)
        write_result(output / "campaign-segment.json", result)
    return result


def worker(args, config: dict) -> dict:
    from fort_gym.bench.run.campaign_environment import NativeCampaignEnvironment
    from fort_gym.bench.run.campaign_save import NativeSaveSnapshotter

    output = args.output.resolve()
    runtime = output / "runtime"
    if Path(os.environ["DFROOT"]).resolve() != runtime:
        raise ValueError("Worker DFROOT does not identify its isolated runtime")
    environment = NativeCampaignEnvironment(expected_dfroot=runtime)
    try:
        agent = make_agent(config, args.model, output / "spend.jsonl", persist_dispatches=True)
        return run_segment(
            agent=agent,
            environment=environment,
            snapshotter=NativeSaveSnapshotter(dfroot=runtime),
            output=output,
            config=config,
            campaign_id=args.campaign_id,
            model=args.model,
            revision=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            checkpoint=args.checkpoint,
            latest_usage=args.latest_usage,
        )
    finally:
        environment.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--snapshot-sha256")
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--latest-usage", type=Path)
    parser.add_argument("--port", type=int, default=5501)
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    config = load_segment_config(args.config, args.model)
    if (args.checkpoint is None) != (args.latest_usage is None):
        parser.error("Resume requires both checkpoint and latest-usage")
    if args.checkpoint is not None and args.snapshot is not None:
        parser.error("Choose a checkpoint or a starting snapshot, not both")
    if args.worker:
        worker(args, config)
        return
    if args.source is None or (
        args.checkpoint is None and (args.snapshot is None or args.snapshot_sha256 is None)
    ):
        parser.error("Supply a source runtime and a checkpoint or digest-bound snapshot")
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise ValueError("The existing authorized project provider credential must be supplied")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"]):
        raise ValueError("Campaign segments require a clean committed checkout")
    source_kind = "native_snapshot"
    snapshot, digest = args.snapshot, args.snapshot_sha256
    if args.checkpoint is not None:
        snapshot = args.checkpoint
        digest = hashlib.sha256((snapshot / "checkpoint.json").read_bytes()).hexdigest()
        source_kind = "campaign_checkpoint"

    def play(runtime, environment, loaded):
        worker_env = {
            **environment,
            "OPENROUTER_API_KEY": os.environ["OPENROUTER_API_KEY"],
            "FORT_GYM_DISABLE_DOTENV": "1",
            "DFROOT": str(runtime.resolve()),
            "DFHACK_ENABLED": "1",
            "DF_PROTO_ENABLED": "1",
            "DFHACK_HOST": "127.0.0.1",
            "DFHACK_PORT": str(args.port),
            "FORT_GYM_DFHACK_COMPLETE_DIG": "0",
            "ARTIFACTS_DIR": str(args.output.resolve() / "unused-artifacts"),
            "FORT_GYM_DB_PATH": str(args.output.resolve() / "unused-registry.sqlite"),
            "OPENROUTER_TIMEOUT_SECONDS": "60",
        }
        command = [
            sys.executable,
            "-m",
            "scripts.campaign_segment",
            "--worker",
            "--config",
            str(args.config.resolve()),
            "--model",
            args.model,
            "--campaign-id",
            args.campaign_id,
            "--output",
            str(args.output.resolve()),
        ]
        if args.checkpoint is not None:
            command += [
                "--checkpoint",
                str(args.checkpoint.resolve()),
                "--latest-usage",
                str(args.latest_usage.resolve()),
            ]
        with (args.output / "worker.log").open("xb") as stream:
            subprocess.run(
                command,
                env=worker_env,
                stdout=stream,
                stderr=subprocess.STDOUT,
                timeout=900,
                check=True,
            )
        result = json.loads((args.output / "campaign-segment.json").read_text())
        return {
            key: result.get(key)
            for key in ("status", "usage", "next_step", "new_checkpoint_verified")
        }

    result = run_isolated(
        source=args.source,
        snapshot=snapshot,
        digest=digest,
        source_kind=source_kind,
        output=args.output,
        port=args.port,
        revision=revision,
        work=play,
        hook_source=Path(__file__).resolve().parents[1] / "hook",
    )
    from scripts.campaign_profile import report_segment

    write_result(args.output / "campaign-profile.json", report_segment(args.output))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
