"""Bind matched continuations to actual own-save state before any model dispatch.

This module owns no VM and sends no game input. The standalone offline command
uses the frozen native readers; the host owner can reuse the same origin and
loaded-state checks before answering its first exchange request.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from typing import Any

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
FRESH = ROOT / "experiments/keyboard_binding_comparison_20260911"
FRESH_OWNER_SHA = "d9db194daee6f0d038e05716a21535cf3276cb2072103241ae5a5c4e09cc991c"
REVISION = "d22f28d99f4fd103188979e964e148139d3f3efd"


def require(value: bool, message: str) -> None:
    if not value:
        raise ValueError(message)


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path: Path) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), "Expected a regular evidence file")
    require(path.stat().st_size <= 4 * 1024 * 1024, "Evidence object is oversized")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in items:
            require(key not in result, "Duplicate evidence key")
            result[key] = item
        return result

    def constant(value: str) -> None:
        raise ValueError("Nonfinite evidence value: " + value)

    value = json.loads(path.read_text(), object_pairs_hook=pairs, parse_constant=constant)
    require(isinstance(value, dict), "Evidence must be an object")
    return value


def prepared_window(root: Path, campaign_id: str) -> dict[str, Any]:
    """Keep the root reporting package separate from frozen native imports."""
    raw = subprocess.check_output(
        [
            sys.executable,
            "-m",
            "scripts.campaign_displayed_key_window",
            "--campaign-id",
            campaign_id,
        ],
        cwd=root,
        text=True,
        timeout=30,
    )
    return json.loads(raw)


def load_native() -> Any:
    """Use the exact native checkout in a fresh process, never a mixed package."""
    require(
        not any(k == "fort_gym" or k.startswith("fort_gym.") for k in sys.modules),
        "Native inspection requires a fresh standalone process",
    )
    path = FRESH / "local_owner.py"
    require(sha(path) == FRESH_OWNER_SHA, "Frozen fresh-start owner changed")
    spec = importlib.util.spec_from_file_location("continuation_frozen_owner", path)
    assert spec is not None and spec.loader is not None
    owner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(owner)
    require(
        subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=owner.WORKTREE, text=True).strip()
        == REVISION,
        "Native revision changed",
    )
    require(
        not subprocess.check_output(["git", "status", "--porcelain"], cwd=owner.WORKTREE),
        "Native checkout is dirty",
    )
    owner.initialize()
    from fort_gym.bench.agent.campaign_keyboard import CodexKeyboardAgent
    from fort_gym.bench.eval.campaign import read_campaign_progress
    from fort_gym.bench.eval.campaign_profile import metrics_from_state
    from fort_gym.bench.run.campaign_checkpoint import verify_checkpoint
    from fort_gym.bench.run.campaign_loop import reconciled_usage
    from fort_gym.bench.run.keyboard_config import load_window
    from fort_gym.bench.run.keyboard_window_courier import window_bounds

    return SimpleNamespace(
        owner=owner,
        agent=CodexKeyboardAgent,
        progress=read_campaign_progress,
        metrics=metrics_from_state,
        verify_checkpoint=verify_checkpoint,
        reconcile=reconciled_usage,
        load_window=load_window,
        window_bounds=window_bounds,
    )


def prior_feedback(runner: dict[str, Any]) -> dict[str, Any] | None:
    """Match the frozen loop's projection, without supplying a strategy or repair."""
    last = runner.get("last_result")
    if last is None:
        return None
    require(
        isinstance(last, dict) and "restart" not in last,
        "Matched first windows cannot inherit a restart",
    )
    native = last.get("result", {})
    value = {
        "accepted": last.get("accepted"),
        "reason": last.get("why"),
        "keys_confirmed": native.get("keys_confirmed"),
        "command_mutation": native.get("command_mutation"),
    }
    if "tick_feedback" in last:
        value["simulation"] = last["tick_feedback"]
    return value


def inspect_origin(root: Path, window_path: Path, native: Any) -> dict[str, Any]:
    """Verify real save files and restore actual model state without an inference."""
    window = read(window_path)
    expected = prepared_window(root, window["expected_campaign_id"])
    require(window == expected, "Window differs from the indexed own-save preparation")
    identity = expected["expected_campaign_id"]  # Validated against the fixed six slots.
    condition_path = (
        root / "experiments/keyboard_binding_comparison_20260911" / window["original_condition"]
    )
    condition, parsed = native.load_window(condition_path, window_path)
    require(
        parsed == window
        and sha(condition_path) == window["source_condition_sha256"]
        and native.window_bounds(condition, window) == (64, 23340),
        "Native continuation limits differ",
    )
    attempt = native.owner.BASE / identity / "attempt"
    checkpoint = attempt / "evidence/astra/segment-0/checkpoint"
    manifest = native.verify_checkpoint(checkpoint)
    payload = manifest["payload"]
    require(
        manifest["sha256"] == window["continuation_checkpoint_sha256"]
        and payload["campaign_id"] == identity
        and payload["next_step"] == 64
        and payload["code_revision"] == REVISION,
        "Wrong own-save checkpoint",
    )
    audit = read(attempt / "terminal-review.json")
    require(
        sha(attempt / "terminal-review.json") == window["source_audit_sha256"]
        and audit["passed"] is True
        and audit["campaign_id"] == identity
        and audit["model"] == condition["model"]
        and audit["responses"] == 64
        and audit["new_tokens"] == window["returned_tokens_before_window"]
        and audit["saved_elapsed_ticks"] == window["saved_elapsed_ticks_before_window"]
        and audit["checkpoint_sha256"] == manifest["sha256"]
        and audit["native_cleanup_verified"] is True
        and audit["vm_teardown_verified"] is True,
        "Parent terminal audit differs",
    )
    saved, runner = read(checkpoint / "agent.json"), read(checkpoint / "runner.json")
    usage = (checkpoint / "usage.jsonl").read_bytes()
    require(
        usage == (checkpoint.parent / "loop/usage.jsonl").read_bytes(),
        "Parent has usage after its saved boundary",
    )

    def no_decision(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("Offline state restoration cannot call a model")

    agent = native.agent(
        decision=no_decision,
        **{
            key: condition[key]
            for key in (
                "max_dispatches",
                "max_total_tokens",
                "max_advance_ticks",
                "model",
                "reasoning_effort",
                "control_profile",
            )
        },
    )
    agent.restore_campaign_state(saved, campaign_id=identity)
    require(
        agent.export_campaign_state() == saved
        and agent.prompt_profile == condition["prompt_profile"]
        and agent.usage == native.reconcile(saved, usage),
        "Saved model state changed",
    )
    require(
        all(
            agent.usage[k] == 64
            for k in (
                "accounted_responses",
                "returned_responses",
                "dispatched_requests",
            )
        )
        and agent.usage["total_tokens"] == window["returned_tokens_before_window"],
        "Parent usage does not match its result",
    )
    require(runner.get("discontinuities", []) == [], "Undeclared parent discontinuity")
    require(
        all(
            runner[k] == condition[k]
            for k in ("observation_profile", "advance_policy", "max_advance_ticks")
        ),
        "Parent runner conditions differ",
    )
    require(
        native.progress(checkpoint / "trace.jsonl")["elapsed_ticks"]
        == window["saved_elapsed_ticks_before_window"],
        "Parent elapsed time differs",
    )
    require(
        native.verify_checkpoint(checkpoint) == manifest,
        "Parent changed during inspection",
    )
    return {
        "window": window,
        "condition": condition,
        "checkpoint": checkpoint,
        "manifest": manifest,
        "agent": saved,
        "runner": runner,
        "metrics": audit["saved_metrics"],
        "feedback": prior_feedback(runner),
        "prefix_sha256": {name: sha(checkpoint / name) for name in ("trace.jsonl", "usage.jsonl")},
        "dispatch_prefix_sha256": {
            "trace.jsonl": sha(checkpoint / "trace.jsonl"),
            "usage.jsonl": hashlib.sha256(usage + decision_started_bytes(64)).hexdigest(),
        },
    }


def decision_started_bytes(next_step: int) -> bytes:
    """Match the pinned native loop's pre-dispatch journal marker exactly."""
    require(type(next_step) is int and next_step == 64, "Unexpected initial dispatch cursor")
    return (
        json.dumps({"type": "decision_started", "step": next_step}, allow_nan=False) + "\n"
    ).encode()


def verify_loaded_state(
    origin: dict[str, Any],
    *,
    agent: dict,
    history: dict,
    before: dict,
    prefix_sha256: dict,
    request: dict,
    metrics: Any,
) -> dict[str, Any]:
    """Gate the first reply on unmodified native restore; menus may reload differently."""
    require(agent == origin["agent"], "Native load changed saved agent state")
    require(history == {"discontinuities": []}, "Native load changed saved history")
    require(
        prefix_sha256 == origin["dispatch_prefix_sha256"],
        "Native load changed its original prefixes or exact pending-dispatch marker",
    )
    saved = origin["manifest"]["payload"]["native_save"]
    require(
        type(before.get("year")) is int
        and type(before.get("year_tick")) is int
        and before["year"] == saved["year"]
        and before["year_tick"] == saved["year_tick"]
        and before.get("pause_state") is True,
        "Native load advanced or unpaused the game",
    )
    require(
        metrics(before) == origin["metrics"],
        "Native load changed saved fortress metrics",
    )
    condition = origin["condition"]
    require(
        request.get("memory") == origin["agent"]["memory"]
        and request.get("feedback") == origin["feedback"],
        "First request changed saved memory or feedback",
    )
    require(
        all(
            request.get(k) == condition[k]
            for k in (
                "model",
                "reasoning_effort",
                "control_profile",
                "prompt_profile",
                "bindings_sha256",
            )
        )
        and [request["screen"]["width"], request["screen"]["height"]] == condition["screen_size"],
        "First request changed the declared model or controls",
    )
    return {
        "schema_version": "fortgym.matched-continuation-load-gate/v2",
        "passed": True,
        "campaign_id": origin["window"]["expected_campaign_id"],
        "checkpoint_sha256": origin["manifest"]["sha256"],
        "next_step": 64,
        "original_prefix_sha256": origin["prefix_sha256"],
        "first_dispatch_prefix_sha256": prefix_sha256,
        "exact_decision_started_marker_verified": True,
        "memory_usage_feedback_and_history_preserved": True,
        "native_clock_and_metrics_preserved": True,
        "model_calls_by_gate": 0,
        "gameplay_inputs_by_gate": 0,
        "new_checkpoint_verified": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", type=Path, required=True)
    args = parser.parse_args()
    origin = inspect_origin(ROOT, args.window, load_native())
    window = origin["window"]
    print(
        json.dumps(
            {
                "schema_version": "fortgym.offline-matched-origin/v1",
                "passed": True,
                "campaign_id": window["expected_campaign_id"],
                "checkpoint_sha256": origin["manifest"]["sha256"],
                "window_sha256": sha(args.window),
                "retained_responses": 64,
                "retained_tokens": window["returned_tokens_before_window"],
                "retained_elapsed_ticks": window["saved_elapsed_ticks_before_window"],
                "model_calls": 0,
                "gameplay_inputs": 0,
                "vm_operations": 0,
                "fresh_native_reload_performed": False,
                "continuation_launched": False,
            }
        )
    )


if __name__ == "__main__":
    main()
