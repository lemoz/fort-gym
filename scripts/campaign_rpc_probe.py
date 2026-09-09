"""Provider-free direct-RPC observations across two fresh loads of one save."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fort_gym.bench.agent.keyboard_exchange import publish, read
from fort_gym.bench.run.campaign_resources import capture_resources
from scripts.campaign_keyboard_native import file_digest, verify_source
from scripts.campaign_load_smoke import run_isolated
from scripts.campaign_process import run_worker, termination_as_interrupt


def worker(args) -> dict:
    from fort_gym.bench import dfhack_exec
    from fort_gym.bench.run.campaign_environment import NativeCampaignEnvironment
    from fort_gym.bench.env.native_key_catalog import NATIVE_PROFILE

    def forbidden_cli(*unused, **kwargs):
        raise AssertionError("Direct RPC probe attempted a CLI fallback")

    dfhack_exec.run_dfhack = forbidden_cli
    before = capture_resources()
    observations = []
    environment = NativeCampaignEnvironment(
        expected_dfroot=args.runtime, control_profile=NATIVE_PROFILE,
        private_measurement_profile="fortgym.campaign-food-measurement/v1",
    )
    try:
        screen = environment.screen_capture()
        for _ in range(16):
            state = environment.observe()
            assert (state["year"], state["year_tick"], state["pause_state"]) == (30, 223383, True)
            food = state["private_food_measurement"]
            observations.append({
                "year": state["year"], "year_tick": state["year_tick"],
                "population": state["population"], "drink": state["stocks"]["drink"],
                "food_available": food["available"],
                "food_inventory": food.get("inventory"),
                "food_error_type": food.get("error_type"),
                "resources": capture_resources(),
            })
        assert environment.screen_capture() == screen
    finally:
        environment.close()
    result = {
        "schema_version": "fortgym.direct-rpc-native-probe/v1",
        "model_calls": 0, "gameplay_actions": 0, "gameplay_ticks_requested": 0,
        "transport": "native-rpc", "cli_fallback_forbidden": True,
        "calendar_unchanged": True, "screen_unchanged": True,
        "before": before, "after": capture_resources(), "observations": observations,
    }
    publish(args.output, result)
    return result


def run(args) -> dict:
    args.output.mkdir(mode=0o700, exist_ok=False)
    original = file_digest(args.checkpoint / "checkpoint.json")
    results = []
    for index in range(2):
        receipt = args.output / f"worker-{index}.json"

        def observe(runtime, environment, loaded):
            worker_env = {
                **environment, "FORT_GYM_DISABLE_DOTENV": "1",
                "DFROOT": str(runtime), "DFHACK_ENABLED": "1", "DF_PROTO_ENABLED": "1",
                "DFHACK_HOST": "127.0.0.1", "DFHACK_PORT": str(5590 + index),
                "FORT_GYM_DFHACK_TRANSPORT": "native-rpc",
                "FORT_GYM_DFHACK_COMPLETE_DIG": "0",
                "ARTIFACTS_DIR": str(args.output / "unused-artifacts"),
                "FORT_GYM_DB_PATH": str(args.output / "unused-registry.sqlite"),
            }
            with (args.output / f"worker-{index}.log").open("xb") as log:
                run_worker(
                    [sys.executable, "-m", "scripts.campaign_rpc_probe", "worker",
                     "--runtime", str(runtime), "--output", str(receipt)],
                    env=worker_env, stdout=log, timeout=300,
                )
            return read(receipt)

        result = run_isolated(
            source=args.source, snapshot=args.checkpoint, digest=original,
            source_kind="campaign_checkpoint", output=args.output / f"runtime-{index}",
            port=5590 + index, revision=args.revision, work=observe,
            hook_source=Path(__file__).resolve().parents[1] / "hook",
            minimum_free_bytes=1073741824, screen_size=(120, 40),
        )
        assert result["cleanup_verified"] is True
        results.append(result)
    assert file_digest(args.checkpoint / "checkpoint.json") == original
    result = {
        "schema_version": "fortgym.direct-rpc-load-pair/v1",
        "source_revision": args.revision, "source_checkpoint_file_sha256": original,
        "original_checkpoint_unchanged": True, "fresh_loads": len(results),
        "native_observations": 32, "model_calls": 0, "gameplay_ticks_requested": 0,
        "cleanup_verified": True, "results": results,
    }
    publish(args.output / "result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    native = sub.add_parser("run")
    native.add_argument("--source", type=Path, required=True)
    native.add_argument("--checkpoint", type=Path, required=True)
    native.add_argument("--revision", required=True)
    child = sub.add_parser("worker")
    child.add_argument("--runtime", type=Path, required=True)
    for command in (native, child):
        command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with termination_as_interrupt():
        if args.command == "run":
            verify_source(args.revision)
            result = run(args)
        else:
            result = worker(args)
    print(json.dumps({"completed": True, "schema_version": result["schema_version"]}))


if __name__ == "__main__":
    main()
