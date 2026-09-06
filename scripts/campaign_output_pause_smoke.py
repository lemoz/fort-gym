"""Provider-free native v3 recovery: one runtime, two serial process lifetimes.

The first synthetic decision accounts usage but returns no action. Save, tear
down, verify the on-disk save still equals the checkpoint, restart, restore, then
issue one fresh 20-tick WAIT fixture. This is not autonomous-play evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from fort_gym.bench.agent.base import Agent
from fort_gym.bench.agent.campaign_local import LocalOutputLimitPause
from fort_gym.bench.env.actions import parse_action
from fort_gym.bench.run.campaign_checkpoint import verify_checkpoint
from fort_gym.bench.run.campaign_loop import CampaignLoop, CampaignNoActionPause
from fort_gym.bench.tick_receipt import MAX_REQUEST_OVERSHOOT_TICKS, calendar_elapsed_ticks
from scripts.campaign_load_smoke import run_isolated
from scripts.campaign_process import run_worker, termination_as_interrupt
from scripts.campaign_restart import restart_latest_checkpoint

CAMPAIGN_ID = "native-output-pause-fixture-v1"
MODEL = "provider-free-output-pause-fixture/v1"


class OutputPauseFixtureAgent(Agent):
    """Two synthetic responses, no provider client, no actual token charges."""

    def __init__(self) -> None:
        self.campaign_id: str | None = None
        self.decisions = 0

    def set_campaign_context(self, *, campaign_id: str) -> None:
        self.campaign_id = campaign_id

    def decide(self, obs_text: str, obs_json: dict) -> dict:
        if self.decisions >= 2:
            raise ValueError("Output-pause fixture permits only two synthetic decisions")
        self.decisions += 1
        if self.decisions == 1:
            raise LocalOutputLimitPause("synthetic fully-accounted no-action fixture")
        return {
            "type": "WAIT",
            "params": {},
            "advance_ticks": 20,
            "intent": "fresh provider-free decision after native v3 restart",
        }

    def export_campaign_state(self) -> dict:
        return {
            "campaign_id": self.campaign_id,
            "configuration": {"model": MODEL, "usage_kind": "synthetic_fixture_only"},
            "memory": {"decisions": self.decisions},
            "usage": {
                "total_tokens": self.decisions * 10,
                "total_cost_usd": "0",
                "dispatched_requests": self.decisions,
                "returned_responses": self.decisions,
                "accounted_responses": self.decisions,
            },
        }

    def restore_campaign_state(self, data: dict, *, campaign_id: str) -> None:
        if (
            data["campaign_id"] != campaign_id
            or data["configuration"] != self.export_campaign_state()["configuration"]
            or type(data["memory"].get("decisions")) is not int
            or data["memory"]["decisions"] != 1
        ):
            raise ValueError("Fixture must restore the one-response no-action boundary")
        self.campaign_id = campaign_id
        self.decisions = 1
        if data != self.export_campaign_state():
            raise ValueError("Synthetic fixture state or usage differs from the checkpoint")


def write_new(path: Path, value: dict) -> None:
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def worker(output: Path, runtime: Path, checkpoint: Path | None, minimum_free_bytes: int) -> dict:
    from fort_gym.bench.run.campaign_environment import NativeCampaignEnvironment
    from fort_gym.bench.run.campaign_save import NativeSaveSnapshotter

    if Path(os.environ["DFROOT"]).resolve() != runtime.resolve():
        raise ValueError("Worker DFROOT differs from its owned runtime")
    environment = NativeCampaignEnvironment(expected_dfroot=runtime)
    try:
        return exercise(
            output=output,
            agent=OutputPauseFixtureAgent(),
            environment=environment,
            checkpoint=checkpoint,
            snapshotter=NativeSaveSnapshotter(
                dfroot=runtime, minimum_free_bytes=minimum_free_bytes
            ),
            revision=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        )
    finally:
        environment.close()


def exercise(*, output, agent, environment, checkpoint, snapshotter, revision) -> dict:
    """Exercise the real campaign loop; only the policy response is synthetic."""
    initial = environment.observe()
    restored = None
    actions = []
    if checkpoint is None:
        loop = CampaignLoop(
            campaign_id=CAMPAIGN_ID,
            agent=agent,
            environment=environment,
            output=output / "campaign",
        )
        try:
            loop.step()
        except CampaignNoActionPause:
            pass
        else:
            raise ValueError("Fixture failed to reach its accounted no-action pause")
        manifest = loop.checkpoint(
            output / "checkpoint", snapshotter=snapshotter, code_revision=revision
        )
        if manifest["schema_version"] != "fortgym.campaign-checkpoint/v3":
            raise ValueError("Output pause did not produce a v3 native checkpoint")
    else:
        loop = CampaignLoop.resume(
            checkpoint,
            agent=agent,
            environment=environment,
            output=output / "campaign",
            latest_usage_path=checkpoint.parent / "campaign/usage.jsonl",
        )
        restored = {"next_step": loop.next_step, "agent_state": agent.export_campaign_state()}
        row = loop.step()
        actions.append(
            {
                "step": row["step"],
                "action": row["action"],
                "tick_advance": row["tick_advance"],
                "previous_step": row["observation"]["agent_plan_control"]["previous_step"],
            }
        )
    result = {
        "schema_version": "fortgym.native-output-pause-worker/v1",
        "provider_calls": 0,
        "usage_kind": "synthetic_fixture_only",
        "autonomous_gameplay": False,
        "initial": initial,
        "final": environment.observe(),
        "next_step": loop.next_step,
        "agent_state": agent.export_campaign_state(),
        "restored": restored,
        "actions": actions,
        "new_checkpoint_created": checkpoint is None,
    }
    write_new(output / "worker-result.json", result)
    return result


def _boundary(state: dict) -> tuple[int, int]:
    year, tick = state.get("year"), state.get("year_tick")
    if (
        type(year) is not int
        or year < 0
        or type(tick) is not int
        or not 0 <= tick < 403200
        or state.get("pause_state") is not True
    ):
        raise ValueError("Fixture evidence lacks a valid paused native boundary")
    return year, tick


def verify_recovery(first: dict, resumed: dict, checkpoint: Path) -> dict:
    manifest = verify_checkpoint(checkpoint)
    payload = manifest["payload"]
    saved = payload["native_save"]
    saved_agent = json.loads((checkpoint / "agent.json").read_text())
    if (
        manifest["schema_version"] != "fortgym.campaign-checkpoint/v3"
        or payload["next_step"] != 0
        or payload["last_committed_step"] != -1
        or payload["campaign_id"] != CAMPAIGN_ID
        or first["actions"] != []
        or first["next_step"] != 0
        or first["agent_state"] != saved_agent
        or first["new_checkpoint_created"] is not True
        or resumed["new_checkpoint_created"] is not False
        or resumed["restored"] != {"next_step": 0, "agent_state": saved_agent}
        or len(resumed["actions"]) != 1
        or resumed["next_step"] != 1
    ):
        raise ValueError("Fixture did not preserve the v3 no-action state and cursor")
    probe = OutputPauseFixtureAgent()
    probe.restore_campaign_state(saved_agent, campaign_id=CAMPAIGN_ID)
    expected_action = parse_action(probe.decide("", {}))
    row = resumed["actions"][0]
    if (
        row["action"] != expected_action
        or row["step"] != 0
        or row["previous_step"] != -1
        or resumed["agent_state"] != probe.export_campaign_state()
    ):
        raise ValueError("Resumed decision or cumulative synthetic usage differs")
    boundary = saved["year"], saved["year_tick"]
    if any(
        _boundary(state) != boundary
        for state in (first["initial"], first["final"], resumed["initial"])
    ):
        raise ValueError("Native state advanced during the no-action save/restart boundary")
    tick = row["tick_advance"]
    elapsed, error = calendar_elapsed_ticks(
        tick["start_year"], tick["start_tick"], tick["end_year"], tick["end_tick"]
    )
    if (
        error is not None
        or elapsed is None
        or tick.get("ok") is not True
        or (tick["start_year"], tick["start_tick"]) != boundary
        or elapsed != tick["ticks_advanced"]
        or not 20 <= elapsed <= 20 + MAX_REQUEST_OVERSHOOT_TICKS
        or _boundary(resumed["final"]) != (tick["end_year"], tick["end_tick"])
    ):
        raise ValueError("Resumed WAIT lacks a bounded native tick receipt")
    for result in (first, resumed):
        if (
            result["provider_calls"] != 0
            or result["usage_kind"] != "synthetic_fixture_only"
            or result["autonomous_gameplay"] is not False
        ):
            raise ValueError("Fixture provenance is not provider-free synthetic policy")
    return {
        "native_output_pause_recovery_verified": True,
        "checkpoint_schema": manifest["schema_version"],
        "restored_next_step": 0,
        "final_next_step": 1,
        "resumed_requested_ticks": 20,
        "resumed_observed_ticks": elapsed,
        "provider_calls": 0,
        "usage_kind": "synthetic_fixture_only",
        "metered_model_cost_usd": "0",
        "autonomous_gameplay": False,
        "year_two_gameplay_verified": False,
        "final_resumable_checkpoint_created": False,
    }


def run_fixture(args) -> dict:
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all"]):
        raise ValueError("Native output-pause fixture requires a clean committed checkout")
    if not 1024 <= args.port <= 65535 or args.port == 5000:
        raise ValueError("Use a dedicated unprivileged non-production port")
    if args.minimum_free_bytes < 0 or args.growth_allowance_bytes < 0:
        raise ValueError("Fixture disk limits must be nonnegative")
    args.output = args.output.resolve()
    args.output.mkdir(mode=0o700, parents=False, exist_ok=False)
    first_output, resumed_output = args.output / "first", args.output / "resumed"

    def perform(output, checkpoint=None):
        def play(runtime, environment, loaded):
            worker_env = {
                **environment,
                "FORT_GYM_DISABLE_DOTENV": "1",
                "DFROOT": str(runtime),
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
                "scripts.campaign_output_pause_smoke",
                "--worker",
                "--output",
                str(output),
                "--runtime",
                str(runtime),
                "--minimum-free-bytes",
                str(args.minimum_free_bytes),
            ]
            if checkpoint is not None:
                command += ["--checkpoint", str(checkpoint)]
            with (output / "worker.log").open("xb") as stream:
                run_worker(command, env=worker_env, stdout=stream, timeout=300)
            data = json.loads((output / "worker-result.json").read_text())
            return {"provider_calls": 0, "next_step": data["next_step"]}

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
        minimum_free_bytes=args.minimum_free_bytes + args.growth_allowance_bytes,
        checkpoint_copies=1,
    )
    checkpoint = first_output / "checkpoint"
    digest = hashlib.sha256((checkpoint / "checkpoint.json").read_bytes()).hexdigest()
    prior_digest = hashlib.sha256((first_output / "result.json").read_bytes()).hexdigest()
    resumed_runtime = restart_latest_checkpoint(
        previous_output=first_output,
        previous_receipt_sha256=prior_digest,
        checkpoint_sha256=digest,
        output=resumed_output,
        revision=revision,
        minimum_free_bytes=args.minimum_free_bytes,
        growth_allowance_bytes=args.growth_allowance_bytes,
        work=perform(resumed_output, checkpoint),
    )
    result = verify_recovery(
        json.loads((first_output / "worker-result.json").read_text()),
        json.loads((resumed_output / "worker-result.json").read_text()),
        checkpoint,
    )
    if (
        first_runtime["cleanup_verified"] is not True
        or resumed_runtime["cleanup_verified"] is not True
        or resumed_runtime["runtime_path"] != first_runtime["runtime_path"]
    ):
        raise ValueError("Fixture lacks verified teardown of its shared runtime")
    result.update(
        schema_version="fortgym.native-output-pause-smoke/v1",
        code_revision=revision,
        checkpoint_file_sha256=digest,
        first_runtime_receipt_sha256=prior_digest,
        first_cleanup_verified=True,
        resumed_cleanup_verified=True,
        runtime_asset_copies=1,
        minimum_free_bytes=args.minimum_free_bytes,
        growth_allowance_bytes=args.growth_allowance_bytes,
    )
    write_new(args.output / "result.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--snapshot-sha256")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=5501)
    parser.add_argument("--minimum-free-bytes", type=int, default=1073741824)
    parser.add_argument("--growth-allowance-bytes", type=int, default=1048576)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--checkpoint", type=Path)
    args = parser.parse_args()
    with termination_as_interrupt():
        if args.worker:
            if args.runtime is None:
                parser.error("worker requires its explicit owned runtime")
            worker(args.output, args.runtime, args.checkpoint, args.minimum_free_bytes)
            return
        if args.source is None or args.snapshot is None or args.snapshot_sha256 is None:
            parser.error("source, snapshot and snapshot-sha256 are required")
        print(json.dumps(run_fixture(args), sort_keys=True))


if __name__ == "__main__":
    main()
