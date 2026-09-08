"""Resume keyboard campaigns in isolated native game processes.

The outer runtime owner provides game assets, a checkpoint and a credential-free
exchange directory. It owns the container/VM and host courier. This command owns
each copied game process, native checkpoints and retained failure evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

from fort_gym.bench.agent.campaign_keyboard import CodexKeyboardAgent
from fort_gym.bench.agent.keyboard_exchange import (
    MAX_BYTES,
    digest,
    exchange_decision,
    publish,
    read,
)
from fort_gym.bench.run.campaign_checkpoint import verify_checkpoint
from fort_gym.bench.run.campaign_environment import NativeCampaignEnvironment
from fort_gym.bench.run.campaign_loop import reconciled_usage
from fort_gym.bench.run.campaign_save import NativeSaveSnapshotter
from fort_gym.bench.run.keyboard_config import load_window
from fort_gym.bench.run.keyboard_segment import run_keyboard_segment
from fort_gym.bench.run.keyboard_save import (
    LEGACY_SAVE_PROFILE,
    MENU_SAVE_PROFILE,
    SEMANTIC_SAVE_PROFILES,
    MenuPreservingSnapshotter,
)
from scripts.campaign_load_smoke import run_isolated
from scripts.campaign_process import run_worker, termination_as_interrupt

PROJECT = Path(__file__).resolve().parents[1]
MINIMUM_FREE_BYTES = 1073741824


def file_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_source(revision: str) -> None:
    if re.fullmatch("[a-f0-9]{40}", revision) is None:
        raise ValueError("An exact committed source revision is required")
    if (
        subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=PROJECT, text=True).strip()
        != revision
    ):
        raise ValueError("Executed source differs from the declared revision")
    if subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=all"], cwd=PROJECT
    ):
        raise ValueError("Native windows require a clean committed checkout")


def publish_response(exchange: Path, identifier: str, value: dict) -> None:
    if re.fullmatch("[a-f0-9]{32}", identifier) is None:
        raise ValueError("Invalid exchange request identifier")
    directory = exchange / identifier
    request = read(directory / "request.json")
    if (
        request.get("request_id") != identifier
        or set(value) != {"request_sha256", "result"}
        or value["request_sha256"] != digest(request)
        or not isinstance(value["result"], dict)
    ):
        raise ValueError("Model response does not identify the original request")
    destination = directory / "response.json"
    publish(destination, value)
    if read(destination) != value:
        raise ValueError("Game-user response readback failed")


def worker(args) -> dict:
    condition, window = load_window(args.condition, args.window)
    environment = NativeCampaignEnvironment(
        expected_dfroot=args.runtime,
        control_profile=condition["control_profile"],
        max_advance_ticks=condition["max_advance_ticks"],
        private_measurement_profile=window.get("private_measurement_profile"),
    )
    try:
        profile = window.get("snapshot_profile", LEGACY_SAVE_PROFILE)
        snapshotter = (
            MenuPreservingSnapshotter(
                dfroot=args.runtime,
                screen_capture=environment.screen_capture,
                minimum_free_bytes=MINIMUM_FREE_BYTES,
                profile=profile,
                observe=environment.observe if profile in SEMANTIC_SAVE_PROFILES else None,
            )
            if profile in (MENU_SAVE_PROFILE, *SEMANTIC_SAVE_PROFILES)
            else NativeSaveSnapshotter(
                dfroot=args.runtime,
                minimum_free_bytes=MINIMUM_FREE_BYTES,
            )
        )
        agent = CodexKeyboardAgent(
            decision=lambda screen, memory, feedback: exchange_decision(
                args.exchange,
                screen,
                memory,
                feedback,
                max_advance_ticks=condition["max_advance_ticks"],
                timeout_seconds=condition["exchange_timeout_seconds"],
                **(
                    {"model": condition["model"], "reasoning_effort": condition["reasoning_effort"]}
                    if condition["schema_version"] == "fortgym.codex-keyboard-condition/v2"
                    else {}
                ),
            ),
            max_dispatches=condition["max_dispatches"],
            max_total_tokens=condition["max_total_tokens"],
            max_advance_ticks=condition["max_advance_ticks"],
            model=condition["model"],
            reasoning_effort=condition["reasoning_effort"],
        )
        return run_keyboard_segment(
            agent=agent,
            environment=environment,
            snapshotter=snapshotter,
            output=args.output,
            condition=condition,
            checkpoint=args.checkpoint,
            latest_usage=args.latest_usage,
            steps=window["steps_per_segment"],
            expected_cursor=args.cursor,
            revision=args.revision,
            budget_extension=window.get("budget_extension") if args.extend_budget else None,
            restart_declaration=window.get("restart") if getattr(args, "restart_source", None) else None,
            restart_source=getattr(args, "restart_source", None),
        )
    finally:
        environment.close()


def run_window(args) -> dict:
    condition, window = load_window(args.condition, args.window)
    if type(args.port) is not int or not 1024 <= args.port <= 65535 - window["max_segments"]:
        raise ValueError("The declared window needs distinct bounded local ports")
    manifest = verify_checkpoint(args.checkpoint)
    if manifest["payload"]["next_step"] != window["continuation_from_next_step"]:
        raise ValueError("Checkpoint does not match the declared continuation cursor")
    original_sha = file_digest(args.checkpoint / "checkpoint.json")
    latest = args.latest_usage.read_bytes()
    if window.get("restart") is not None:
        from fort_gym.bench.run.keyboard_restart import prepare_restart

        if getattr(args, "restart_source", None) is None:
            raise ValueError("Declared restart requires its retained failed source")
        prepare_restart(args.checkpoint, args.restart_source, window["restart"], latest)
    elif getattr(args, "restart_source", None) is not None:
        raise ValueError("Undeclared native save-loss restart")
    elif latest != (args.checkpoint / "usage.jsonl").read_bytes():
        raise ValueError("A window requires the fully settled latest checkpoint, not an older save")
    state = read(args.checkpoint / "agent.json")
    if window.get("restart") is None and reconciled_usage(state, latest) != state["usage"]:
        raise ValueError("Checkpoint usage is not settled")
    args.output.mkdir(mode=0o700, exist_ok=False)
    exchange = args.output / "exchange"
    exchange.mkdir(mode=0o700)
    publish(args.output / "condition.json", condition)
    publish(args.output / "window.json", window)
    result = {
        "schema_version": "fortgym.keyboard-window-result/v1",
        "source_revision": args.revision,
        "campaign_id": manifest["payload"]["campaign_id"],
        "snapshot_profile": window.get("snapshot_profile", LEGACY_SAVE_PROFILE),
        "private_measurement_profile": window.get("private_measurement_profile"),
        "status": "failed",
        "segments": [],
        "original_checkpoint_unchanged": False,
        "runtime_cleanup_verified": False,
    }
    checkpoint, usage = args.checkpoint, args.latest_usage
    try:
        for index in range(window["max_segments"]):
            result["runtime_cleanup_verified"] = False
            segment = args.output / f"segment-{index}"
            port = args.port + index
            cursor = window["continuation_from_next_step"] + index * window["steps_per_segment"]

            def play(runtime, environment, loaded):
                worker_env = {
                    **environment,
                    "FORT_GYM_DISABLE_DOTENV": "1",
                    "DFROOT": str(runtime),
                    "DFHACK_ENABLED": "1",
                    "DF_PROTO_ENABLED": "1",
                    "DFHACK_HOST": "127.0.0.1",
                    "DFHACK_PORT": str(port),
                    "FORT_GYM_DFHACK_COMPLETE_DIG": "0",
                    "ARTIFACTS_DIR": str(args.output / "unused-artifacts"),
                    "FORT_GYM_DB_PATH": str(args.output / "unused-registry.sqlite"),
                }
                command = [
                    sys.executable,
                    "-m",
                    "scripts.campaign_keyboard_native",
                    "worker",
                    "--condition",
                    str(args.condition),
                    "--window",
                    str(args.window),
                    "--checkpoint",
                    str(checkpoint),
                    "--latest-usage",
                    str(usage),
                    "--output",
                    str(segment),
                    "--runtime",
                    str(runtime),
                    "--exchange",
                    str(exchange),
                    "--cursor",
                    str(cursor),
                    "--revision",
                    args.revision,
                ]
                if index == 0 and window.get("budget_extension") is not None:
                    command.append("--extend-budget")
                if index == 0 and getattr(args, "restart_source", None) is not None:
                    command.extend(["--restart-source", str(args.restart_source)])
                with (args.output / f"worker-{index}.log").open("xb") as log:
                    try:
                        run_worker(
                            command,
                            env=worker_env,
                            stdout=log,
                            timeout=window["steps_per_segment"]
                            * (condition["exchange_timeout_seconds"] + 120)
                            + 300,
                        )
                    except subprocess.CalledProcessError:
                        # A worker writes its failed segment before exiting.
                        # Preserve that outcome in the window rather than lose
                        # it behind a subprocess error. Never promote success.
                        failed = read(segment / "result.json")
                        if (
                            failed.get("schema_version") != "fortgym.keyboard-segment/v1"
                            or failed.get("source_revision") != args.revision
                            or failed.get("campaign_id") != result["campaign_id"]
                            or failed.get("first_step") != cursor
                            or failed.get("status") not in {"failed", "checkpoint_failed"}
                        ):
                            raise
                        return failed
                return read(segment / "result.json")

            native = run_isolated(
                source=args.source,
                snapshot=checkpoint,
                digest=file_digest(checkpoint / "checkpoint.json"),
                source_kind="campaign_checkpoint",
                output=args.output / f"runtime-{index}",
                port=port,
                revision=args.revision,
                work=play,
                hook_source=PROJECT / "hook",
                minimum_free_bytes=MINIMUM_FREE_BYTES,
                checkpoint_copies=1,
                screen_size=tuple(condition["screen_size"]),
            )
            segment_result = native["experiment"]
            result["segments"].append(segment_result)
            if native["cleanup_verified"] is not True:
                raise ValueError("Native game cleanup was not verified")
            result["runtime_cleanup_verified"] = True
            if (
                segment_result["status"] != "bounded_segment_complete"
                or segment_result["checkpoint_verified"] is not True
            ):
                raise ValueError("Keyboard segment did not produce a settled checkpoint")
            checkpoint, usage = segment / "checkpoint", segment / "loop/usage.jsonl"
            if segment_result["stop_reason"] != "segment_limit":
                result["status"] = "paused"
                break
        else:
            result["status"] = "completed"
        result["runtime_cleanup_verified"] = True
    except Exception as error:
        result.update(error_type=type(error).__name__, error=str(error))
    finally:
        try:
            verify_checkpoint(args.checkpoint)
            result["original_checkpoint_unchanged"] = (
                file_digest(args.checkpoint / "checkpoint.json") == original_sha
            )
        except (OSError, ValueError, RuntimeError):
            result["original_checkpoint_unchanged"] = False
        if not result["original_checkpoint_unchanged"]:
            result["status"] = "failed"
        publish(args.output / "result.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "worker"):
        command = commands.add_parser(name)
        for field in ("condition", "window", "checkpoint", "latest-usage", "output"):
            command.add_argument("--" + field, type=Path, required=True)
        command.add_argument("--revision", required=True)
        command.add_argument("--restart-source", type=Path)
        if name == "run":
            command.add_argument("--source", type=Path, required=True)
            command.add_argument("--port", type=int, required=True)
        else:
            command.add_argument("--runtime", type=Path, required=True)
            command.add_argument("--exchange", type=Path, required=True)
            command.add_argument("--cursor", type=int, required=True)
            command.add_argument("--extend-budget", action="store_true")
    response = commands.add_parser("publish-response")
    response.add_argument("--exchange", type=Path, required=True)
    response.add_argument("--request-id", required=True)
    probe = commands.add_parser("probe")
    probe.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command in ("probe", "publish-response"):
        raw = sys.stdin.buffer.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("Response exceeds exchange bound")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("Response must be a JSON object")
        if args.command == "probe":
            publish(args.output, value)
            if read(args.output) != value:
                raise ValueError("Game-user probe failed")
        else:
            publish_response(args.exchange, args.request_id, value)
        print(json.dumps({"published_and_read_verified": True}), flush=True)
        return
    for field in (
        "condition",
        "window",
        "checkpoint",
        "latest_usage",
        "output",
        "source",
        "runtime",
        "exchange",
        "restart_source",
    ):
        if getattr(args, field, None) is not None:
            setattr(args, field, getattr(args, field).resolve())
    verify_source(args.revision)
    with termination_as_interrupt():
        result = run_window(args) if args.command == "run" else worker(args)
    print(json.dumps(result), flush=True)
    if result["status"] not in {"completed", "paused", "bounded_segment_complete"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
