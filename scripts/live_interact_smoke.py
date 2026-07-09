#!/usr/bin/env python3
"""Execute one zero-tick governed INTERACT against the current paused DF view."""

from __future__ import annotations

import argparse
import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict

from fort_gym.bench.agent.base import Agent
from fort_gym.bench.env.actions import INTERACT_ALLOWED_VIEWSCREEN_TYPES
from fort_gym.bench.run.runner import run_once


class OneInteractAgent(Agent):
    def __init__(self, operation: str) -> None:
        self.operation = operation
        self.calls = 0

    def decide(self, obs_text: str, obs_json: Dict[str, Any]) -> Dict[str, Any]:
        self.calls += 1
        return {
            "type": "INTERACT",
            "params": {"operation": self.operation},
            "intent": "exercise one bounded paused-dialog input",
            "advance_ticks": 0,
        }


def verify_trace_row(row: Dict[str, Any]) -> Dict[str, Any]:
    action = row.get("action") if isinstance(row.get("action"), dict) else {}
    execute = row.get("execute") if isinstance(row.get("execute"), dict) else {}
    interaction = row.get("interaction") if isinstance(row.get("interaction"), dict) else {}
    tick_advance = row.get("tick_advance") if isinstance(row.get("tick_advance"), dict) else {}
    gameplay_proof = (
        row.get("gameplay_proof") if isinstance(row.get("gameplay_proof"), dict) else {}
    )
    checks = {
        "one_interact_action": action.get("type") == "INTERACT",
        "explicit_zero_ticks": action.get("advance_ticks") == 0,
        "validation_passed": (row.get("validation") or {}).get("valid") is True,
        "execution_accepted": execute.get("accepted") is True,
        "governed_provenance": execute.get("provenance") == "dfhack_governed",
        "no_progress_credit": (
            execute.get("gameplay_progress_eligible") is False and gameplay_proof.get("ok") is False
        ),
        "one_key_sent": interaction.get("keys_sent") == 1,
        "paused_before_and_after": (
            interaction.get("pause_before") is True and interaction.get("pause_after") is True
        ),
        "allowlisted_before_attested_after": (
            interaction.get("viewscreen_before") in INTERACT_ALLOWED_VIEWSCREEN_TYPES
            and interaction.get("viewscreen_after") not in (None, "", "unknown")
        ),
        "screen_hashes_recorded": bool(
            interaction.get("screen_before_sha256") and interaction.get("screen_after_sha256")
        ),
        "zero_ticks_advanced": int(tick_advance.get("ticks_advanced") or 0) == 0,
        "after_screen_recorded": bool(row.get("screen_text_after_interaction")),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "interaction": interaction,
        "terminal_reason": row.get("terminal_reason"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--operation",
        choices=("confirm", "cancel", "up", "down", "left", "right"),
        default="confirm",
    )
    parser.add_argument("--run-id", default=f"live-interact-{uuid.uuid4().hex[:10]}")
    parser.add_argument(
        "--verify-trace",
        type=Path,
        help="Verify an existing trace without sending another interface input.",
    )
    args = parser.parse_args()

    if args.verify_trace is not None:
        rows = [
            json.loads(line) for line in args.verify_trace.read_text(encoding="utf-8").splitlines()
        ]
        result = verify_trace_row(rows[-1] if rows else {})
        result.update({"trace_path": str(args.verify_trace), "verification_only": True})
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["ok"] else 1

    agent = OneInteractAgent(args.operation)
    run_id = run_once(
        agent,
        backend="dfhack",
        model="dfhack-governed-scripted",
        max_steps=1,
        ticks_per_step=1,
        run_id=args.run_id,
        preserve_save=True,
    )
    trace_path = (
        Path(os.environ.get("ARTIFACTS_DIR", "fort_gym/artifacts")) / run_id / "trace.jsonl"
    )
    rows = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    result = verify_trace_row(rows[-1] if rows else {})
    result.update({"run_id": run_id, "agent_calls": agent.calls, "trace_path": str(trace_path)})
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] and agent.calls == 1 else 1


if __name__ == "__main__":
    raise SystemExit(main())
