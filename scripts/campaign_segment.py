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
import time
from pathlib import Path

from fort_gym.bench.run.campaign_config import (
    LOCAL_SCHEMA,
    decision_time_reserve,
    load_segment_config,
)
from scripts.campaign_development import make_agent
from scripts.campaign_load_smoke import run_isolated
from scripts.campaign_process import run_worker, termination_as_interrupt


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
    on_progress=None,
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

    def report_progress(state):
        if on_progress is not None:
            try:
                result["usage"] = agent.export_campaign_state()["usage"]
                on_progress(result, loop, state)
            except Exception as error:
                # A public projection failure must not change the policy or game.
                # The feed becomes stale; the private result retains this fault.
                result["progress_reporting_error_type"] = type(error).__name__

    try:
        result["native_start"] = environment.observe()
        if checkpoint is None:
            loop = CampaignLoop(
                campaign_id=campaign_id,
                agent=agent,
                environment=environment,
                output=output / "campaign",
                max_advance_ticks=config["max_advance_ticks"],
                observation_profile=config.get("observation_profile", "governed_review/v1"),
                advance_policy=config.get("advance_policy", "accepted_only/v1"),
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
                observation_profile=config.get("observation_profile", "governed_review/v1"),
                advance_policy=config.get("advance_policy", "accepted_only/v1"),
            )
        result["first_step"] = loop.next_step
        report_progress(result["native_start"])
        started = time.monotonic()
        time_budget = config.get("segment_time_budget_seconds")
        result["segment_stop_reason"] = "step_limit"
        for _ in range(config["max_steps"]):
            # Stop at the existing boundary when a cap is already reached, without
            # starting a failed decision or mutating the agent's gameplay memory.
            if agent.dispatches >= config["max_dispatches"]:
                raise GovernedBudgetCapError("Campaign dispatch allowance reached")
            agent._pre_dispatch_gate()
            if time_budget is not None and (
                time.monotonic() - started + decision_time_reserve(config) >= time_budget
            ):
                result["segment_stop_reason"] = "time_slice"
                break
            row = loop.step()
            result["segment_committed_steps"] += 1
            report_progress(row["state_after_advance"])
        result["status"] = "bounded_segment_complete"
    except GovernedBudgetCapError as error:
        result.update(
            status="budget_limited_pause", error_type=type(error).__name__, error=str(error)
        )
    except Exception as error:
        result.update(status="failed", error_type=type(error).__name__, error=str(error))
        terminal_code = getattr(error, "terminal_code", None)
        if isinstance(terminal_code, str):
            result["terminal_code"] = terminal_code
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
        report_progress(result.get("native_final"))
        write_result(output / "campaign-segment.json", result)
    return result


def worker(args, config: dict) -> dict:
    from fort_gym.bench.run.campaign_environment import NativeCampaignEnvironment
    from fort_gym.bench.run.campaign_save import NativeSaveSnapshotter

    output = args.output.resolve()
    runtime = output / "runtime"
    if Path(os.environ["DFROOT"]).resolve() != runtime:
        raise ValueError("Worker DFROOT does not identify its isolated runtime")
    environment = NativeCampaignEnvironment(
        expected_dfroot=runtime,
        workshop_placement_policy=config.get("workshop_placement_policy", "strict_floor/v1"),
    )
    try:
        public_feed = None
        if getattr(args, "public_campaign_dir", None) is not None:
            from fort_gym.bench.run.campaign_feed import CampaignFeed

            public_feed = CampaignFeed(
                args.public_campaign_dir,
                campaign_id=args.campaign_id,
                segment_id=output.name,
                model=args.model,
                config=config,
                revision=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            )
        options = {}
        if config.get("schema_version") == LOCAL_SCHEMA:
            options["local_endpoint"] = args.local_endpoint
        agent = make_agent(
            config, args.model, output / "spend.jsonl", persist_dispatches=True, **options
        )
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
            on_progress=public_feed.progress if public_feed is not None else None,
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
    parser.add_argument(
        "--local-endpoint", help="Literal loopback endpoint for a declared local condition"
    )
    parser.add_argument(
        "--public-campaign-dir",
        type=Path,
        help="Opt in to website-safe summaries in a dedicated shared directory",
    )
    args = parser.parse_args()
    config = load_segment_config(args.config, args.model)
    if (args.checkpoint is None) != (args.latest_usage is None):
        parser.error("Resume requires both checkpoint and latest-usage")
    if args.checkpoint is not None and args.snapshot is not None:
        parser.error("Choose a checkpoint or a starting snapshot, not both")
    if args.worker:
        worker(args, config)
        return
    with termination_as_interrupt():
        print(json.dumps(launch_segment(args, config), sort_keys=True))


def launch_segment(args, config: dict) -> dict:
    """Own exactly one isolated runtime, shared by the CLI and serial controller."""
    if args.source is None or (
        args.checkpoint is None and (args.snapshot is None or args.snapshot_sha256 is None)
    ):
        raise ValueError("Supply a source runtime and a checkpoint or digest-bound snapshot")
    local = config.get("schema_version") == LOCAL_SCHEMA
    if local:
        from fort_gym.bench.agent.campaign_local import verify_local_model

        if getattr(args, "local_endpoint", None) is None:
            raise ValueError("Local campaigns require an explicit loopback endpoint")
        verify_local_model(args.local_endpoint, config, args.model)
    elif not os.environ.get("OPENROUTER_API_KEY"):
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
    public_feed = None
    if args.public_campaign_dir is not None:
        from fort_gym.bench.run.campaign_feed import CampaignFeed, initialize_feed

        initialize_feed(args.public_campaign_dir)
        public_feed = CampaignFeed(
            args.public_campaign_dir,
            campaign_id=args.campaign_id,
            segment_id=args.output.name,
            model=args.model,
            config=config,
            revision=revision,
        )
        public_feed.start(resume=args.checkpoint is not None)

    def play(runtime, environment, loaded):
        worker_env = {
            **environment,
            "OPENROUTER_API_KEY": "" if local else os.environ["OPENROUTER_API_KEY"],
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
        if args.public_campaign_dir is not None:
            command += ["--public-campaign-dir", str(args.public_campaign_dir.resolve())]
        if local:
            command += ["--local-endpoint", args.local_endpoint]
        with (args.output / "worker.log").open("xb") as stream:
            run_worker(
                command,
                env=worker_env,
                stdout=stream,
                timeout=config.get("segment_time_budget_seconds", 600) + 300,
            )
        result = json.loads((args.output / "campaign-segment.json").read_text())
        return {
            key: result.get(key)
            for key in ("status", "usage", "next_step", "new_checkpoint_verified")
        }

    report = None
    try:
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

        report = report_segment(args.output)
        write_result(args.output / "campaign-profile.json", report)
    finally:
        if public_feed is not None:
            # The outer runtime's own finally block runs before this publication.
            try:
                public_feed.finish(args.output, report)
            except Exception as error:
                from scripts.campaign_development import append_event

                if args.output.is_dir():
                    try:
                        append_event(
                            args.output / "publication-errors.jsonl",
                            {"error_type": type(error).__name__},
                        )
                    except OSError:
                        pass  # Keep the original run outcome; stderr still reports this fault.
                print(f"Campaign reporting failed: {type(error).__name__}", file=sys.stderr)
    return result


if __name__ == "__main__":
    main()
