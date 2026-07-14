#!/usr/bin/env python3
"""Run one provider-free live DFHack measurement-calibration scenario.

This is deliberately not a benchmark launcher. It accepts an operator-reviewed
sequence of governed actions, restores the frozen P1 seed, and labels the local
artifacts as calibration-only. Normal Fable/Sol launches remain locked until
the reviewed calibration bundle is pinned by the runtime contract.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
from typing import Any

from fort_gym.bench.agent.base import Agent
from fort_gym.bench.env.actions import parse_action
from fort_gym.bench.eval.fort_eval_easy_p1 import (
    P1_CALIBRATION_MODEL,
    P1_LIVE_CALIBRATION_SCENARIOS,
    P1_MAX_STEPS,
    P1_PROTOCOL,
    P1_RUNTIME_SAVE,
    P1_SEED_SAVE,
    P1_TICKS_PER_STEP,
)
from fort_gym.bench.run.runner import run_once


class CalibrationPlanAgent(Agent):
    """Replay a predeclared sequence through the governed action surface."""

    def __init__(self, actions: list[dict[str, Any]]) -> None:
        self._actions = actions
        self._index = 0

    def decide(self, obs_text: str, obs_json: dict[str, Any]) -> dict[str, Any]:
        del obs_text, obs_json
        if self._index < len(self._actions):
            action = self._actions[self._index]
            self._index += 1
            return action
        return parse_action(
            {
                "type": "WAIT",
                "params": {},
                "intent": "finish the controlled calibration observation window",
                "objective": "Allow queued live DFHack work to settle.",
                "expected_simulation_result": "Existing jobs progress without a new command.",
                "advance_ticks": P1_TICKS_PER_STEP,
            },
            max_advance_ticks=P1_TICKS_PER_STEP,
        )


def _load_plan(path: Path, *, scenario: str) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("calibration plan must be a non-empty JSON action list")
    if len(payload) > P1_MAX_STEPS:
        raise ValueError(f"calibration plan exceeds {P1_MAX_STEPS} actions")
    actions: list[dict[str, Any]] = []
    for index, value in enumerate(payload):
        if not isinstance(value, dict):
            raise ValueError(f"calibration action {index} is not an object")
        actions.append(
            parse_action(value, max_advance_ticks=P1_TICKS_PER_STEP)
        )
    if scenario == "death_cause_fallback" and (
        actions[0].get("type") != "WAIT"
        or int(actions[0].get("advance_ticks") or 0) <= 0
    ):
        raise ValueError(
            "death-cause calibration must begin with a positive-tick WAIT after the fixture"
        )
    return actions


def _require_clean_checkout() -> None:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        check=True,
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        raise RuntimeError(
            "live calibration requires committed measurement code; checkout is dirty"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "scenario", choices=sorted(P1_LIVE_CALIBRATION_SCENARIOS)
    )
    parser.add_argument("plan", type=Path)
    parser.add_argument("--run-id")
    args = parser.parse_args()

    _require_clean_checkout()
    run_id = run_once(
        CalibrationPlanAgent(_load_plan(args.plan, scenario=args.scenario)),
        backend="dfhack",
        model=P1_CALIBRATION_MODEL,
        max_steps=P1_MAX_STEPS,
        ticks_per_step=P1_TICKS_PER_STEP,
        run_id=args.run_id,
        preserve_save=False,
        seed_save=P1_SEED_SAVE,
        runtime_save=P1_RUNTIME_SAVE,
        evaluation_protocol=P1_PROTOCOL,
        measurement_calibration_scenario=args.scenario,
    )
    print(run_id)


if __name__ == "__main__":
    main()
