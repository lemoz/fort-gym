"""Provider-free native continuation fixture using two sequential isolated games.

This issues WAIT fixtures of 10 then 20 ticks, saves after the first, destroys the
first process, loads the checkpoint in a new process, and verifies the second
decision is fresh. It is infrastructure evidence, never autonomous-play evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from fort_gym.bench.agent.base import Agent
from scripts.campaign_load_smoke import run_isolated
from fort_gym.bench.tick_receipt import MAX_REQUEST_OVERSHOOT_TICKS, calendar_elapsed_ticks


class ContinuationFixtureAgent(Agent):
    """No provider client or API key; deterministic decisions for restart testing."""

    def __init__(self) -> None:
        self.campaign_id = None
        self.decisions = 0

    def set_campaign_context(self, *, campaign_id: str) -> None:
        self.campaign_id = campaign_id

    def decide(self, obs_text: str, obs_json: dict) -> dict:
        self.decisions += 1
        if self.decisions > 2:
            raise ValueError("Native continuation fixture has only two decisions")
        return {
            "type": "WAIT",
            "params": {},
            "advance_ticks": self.decisions * 10,
            "intent": f"provider-free native continuation fixture {self.decisions}",
        }

    def export_campaign_state(self) -> dict:
        return {
            "campaign_id": self.campaign_id,
            "configuration": {"model": "provider-free-continuation-fixture/v1"},
            "memory": {"decisions": self.decisions},
            "usage": {
                "total_tokens": 0,
                "total_cost_usd": "0",
                "returned_responses": 0,
                "accounted_responses": 0,
            },
        }

    def restore_campaign_state(self, data: dict, *, campaign_id: str) -> None:
        if data["campaign_id"] != campaign_id:
            raise ValueError("Fixture campaign identity mismatch")
        if data["configuration"] != self.export_campaign_state()["configuration"]:
            raise ValueError("Fixture configuration changed")
        self.campaign_id = campaign_id
        self.decisions = data["memory"]["decisions"]


def worker(output: Path, checkpoint: Path | None, latest_usage: Path | None) -> dict:
    from fort_gym.bench.run.campaign_environment import NativeCampaignEnvironment
    from fort_gym.bench.run.campaign_loop import CampaignLoop
    from fort_gym.bench.run.campaign_save import NativeSaveSnapshotter

    runtime = output.resolve() / "runtime"
    if Path(os.environ["DFROOT"]).resolve() != runtime:
        raise ValueError("Worker DFROOT is not its isolated runtime")
    agent = ContinuationFixtureAgent()
    environment = NativeCampaignEnvironment(expected_dfroot=runtime)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    try:
        initial = environment.observe()
        if checkpoint is None:
            loop = CampaignLoop(
                campaign_id="native-continuation-fixture-v1",
                agent=agent,
                environment=environment,
                output=output / "campaign",
            )
            first = loop.step()
            loop.checkpoint(
                output / "checkpoint",
                snapshotter=NativeSaveSnapshotter(dfroot=runtime),
                code_revision=revision,
            )
            second = loop.step()
            rows = [first, second]
        else:
            if latest_usage is None:
                raise ValueError("Resume requires the first worker's latest usage journal")
            loop = CampaignLoop.resume(
                checkpoint,
                agent=agent,
                environment=environment,
                output=output / "campaign",
                latest_usage_path=latest_usage,
            )
            rows = [loop.step()]
            loop.checkpoint(
                output / "checkpoint",
                snapshotter=NativeSaveSnapshotter(dfroot=runtime),
                code_revision=revision,
            )
        result = {
            "schema_version": "fortgym.native-continuation-worker/v1",
            "provider_calls": 0,
            "reported_model_cost_usd": "0",
            "autonomous_gameplay": False,
            "initial": initial,
            "final": environment.observe(),
            "next_step": loop.next_step,
            "agent_state": agent.export_campaign_state(),
            "actions": [
                {
                    "step": row["step"],
                    "action": row["action"],
                    "tick_advance": row["tick_advance"],
                    "previous_step": row["observation"]["agent_plan_control"]["previous_step"],
                }
                for row in rows
            ],
        }
        with (output / "worker-result.json").open("x") as stream:
            json.dump(result, stream, indent=2, allow_nan=False)
        return result
    finally:
        environment.close()


def verify_continuation(first: dict, resumed: dict) -> dict:
    """Compare evidence at explicit native and decision boundaries."""
    first_actions, resumed_actions = first["actions"], resumed["actions"]
    if len(first_actions) != 2 or len(resumed_actions) != 1:
        raise ValueError("Unexpected continuation fixture action counts")
    expected, actual = first_actions[1], resumed_actions[0]
    if (
        expected["action"] != actual["action"]
        or actual["step"] != 1
        or actual["previous_step"] != 0
    ):
        raise ValueError("Resumed next action or history differs from uninterrupted execution")
    for row, requested in zip(first_actions + resumed_actions, (10, 20, 20)):
        tick = row["tick_advance"]
        elapsed, error = calendar_elapsed_ticks(
            tick["start_year"], tick["start_tick"], tick["end_year"], tick["end_tick"]
        )
        if (
            error is not None
            or tick.get("ok") is not True
            or elapsed != tick["ticks_advanced"]
            or row["action"]["advance_ticks"] != requested
            or not requested <= elapsed <= requested + MAX_REQUEST_OVERSHOOT_TICKS
        ):
            raise ValueError("Fixture did not observe bounded native ticks")
    if first["agent_state"] != resumed["agent_state"] or resumed["next_step"] != 2:
        raise ValueError("Resumed agent state or cursor differs")
    saved = first_actions[0]["tick_advance"]
    if (resumed["initial"]["year"], resumed["initial"]["year_tick"]) != (
        saved["end_year"],
        saved["end_tick"],
    ):
        raise ValueError("Resumed runtime did not start at the saved native boundary")
    for result in (first, resumed):
        tick = result["actions"][-1]["tick_advance"]
        if result["final"].get("pause_state") is not True or (
            result["final"]["year"],
            result["final"]["year_tick"],
        ) != (tick["end_year"], tick["end_tick"]):
            raise ValueError("Final native boundary does not match the committed tick receipt")
    return {
        "native_continuation_fixture_verified": True,
        "autonomous_gameplay": False,
        "year_two_gameplay_verified": False,
        "provider_calls": 0,
        "reported_model_cost_usd": "0",
        "first_process_requested_ticks": 30,
        "resumed_process_requested_ticks": 20,
        "first_process_observed_ticks": sum(
            row["tick_advance"]["ticks_advanced"] for row in first_actions
        ),
        "resumed_process_observed_ticks": actual["tick_advance"]["ticks_advanced"],
        "restored_next_step": 1,
        "final_next_step": 2,
        "resumed_action": deepcopy(actual),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--snapshot-sha256")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=5501)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--latest-usage", type=Path)
    args = parser.parse_args()
    if args.worker:
        worker(args.output, args.checkpoint, args.latest_usage)
        return
    if args.source is None or args.snapshot is None or args.snapshot_sha256 is None:
        parser.error("source, snapshot, and snapshot-sha256 are required")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"]):
        raise ValueError("Native continuation requires a clean committed checkout")
    args.output.mkdir(mode=0o700, parents=False, exist_ok=False)
    first_output, resumed_output = args.output / "first", args.output / "resumed"

    def perform(output: Path, checkpoint: Path | None = None):
        def play(runtime, environment, loaded):
            worker_env = {
                **environment,
                "FORT_GYM_DISABLE_DOTENV": "1",
                "DFROOT": str(runtime.resolve()),
                "DFHACK_ENABLED": "1",
                "DF_PROTO_ENABLED": "1",
                "DFHACK_HOST": "127.0.0.1",
                "DFHACK_PORT": str(args.port),
                "FORT_GYM_DFHACK_COMPLETE_DIG": "0",
                "ARTIFACTS_DIR": str(output / "unused-artifacts"),
                "FORT_GYM_DB_PATH": str(output / "unused-registry.sqlite"),
            }
            command = [
                sys.executable,
                "-m",
                "scripts.campaign_continuation_smoke",
                "--worker",
                "--output",
                str(output),
            ]
            if checkpoint is not None:
                command += [
                    "--checkpoint",
                    str(checkpoint),
                    "--latest-usage",
                    str(first_output / "campaign/usage.jsonl"),
                ]
            with (output / "worker.log").open("xb") as stream:
                subprocess.run(
                    command,
                    env=worker_env,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    timeout=300,
                    check=True,
                )
            data = json.loads((output / "worker-result.json").read_text())
            return {
                "provider_calls": 0,
                "next_step": data["next_step"],
                "autonomous_gameplay": False,
            }

        return play

    first_runtime = run_isolated(
        source=args.source,
        snapshot=args.snapshot,
        digest=args.snapshot_sha256,
        output=first_output,
        port=args.port,
        revision=revision,
        work=perform(first_output),
        hook_source=Path(__file__).resolve().parents[1] / "hook",
    )
    checkpoint = first_output / "checkpoint"
    digest = hashlib.sha256((checkpoint / "checkpoint.json").read_bytes()).hexdigest()
    resumed_runtime = run_isolated(
        source=args.source,
        snapshot=checkpoint,
        digest=digest,
        source_kind="campaign_checkpoint",
        output=resumed_output,
        port=args.port,
        revision=revision,
        work=perform(resumed_output, checkpoint),
        hook_source=Path(__file__).resolve().parents[1] / "hook",
    )
    result = verify_continuation(
        json.loads((first_output / "worker-result.json").read_text()),
        json.loads((resumed_output / "worker-result.json").read_text()),
    )
    result.update(
        schema_version="fortgym.native-continuation-smoke/v1",
        code_revision=revision,
        first_cleanup_verified=first_runtime["cleanup_verified"],
        resumed_cleanup_verified=resumed_runtime["cleanup_verified"],
        checkpoint_file_sha256=digest,
    )
    with (args.output / "result.json").open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
