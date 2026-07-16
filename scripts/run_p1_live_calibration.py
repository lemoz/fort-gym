#!/usr/bin/env python3
"""Run one provider-free live DFHack measurement-calibration scenario.

This is deliberately not a benchmark launcher. It accepts an operator-reviewed
sequence of governed actions, restores the frozen P1 seed, and labels the local
artifacts as calibration-only. Normal Fable/Sol launches remain locked until
the reviewed calibration bundle is pinned by the runtime contract.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import subprocess
from typing import Any

from fort_gym.bench.agent.base import Agent
from fort_gym.bench.env.actions import (
    FINISH_TOPIC_MEETING_OPTION_TEXT,
    INTERACT_ALLOWED_VIEWSCREEN_TYPES,
    parse_action,
    visible_topic_meeting_option,
)
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
    """Replay a predeclared plan with bounded live-ID and UI recovery."""

    _CARPENTER_ORDER_JOBS = frozenset(
        {"barrel", "bed", "bin", "chair", "door", "table"}
    )
    _FURNITURE_GOODS_BY_KIND = {
        "Bed": "bed",
        "Chair": "chair",
        "Door": "door",
        "Table": "table",
    }
    _MAX_PRECONDITION_WAITS = 8

    def __init__(self, actions: list[dict[str, Any]]) -> None:
        self._actions = actions
        self._index = 0
        self._baseline_farm_ids: set[int] | None = None
        self._farm_id_map: dict[int, int] = {}
        self._assigned_farm_ids: set[int] = set()
        self._precondition_waits: dict[tuple[int, str], int] = {}

    @staticmethod
    def _positive_int(value: Any) -> int | None:
        if type(value) is not int:
            return None
        return value if value >= 0 else None

    @classmethod
    def _observed_farm_ids(cls, obs_json: dict[str, Any]) -> set[int]:
        crew = obs_json.get("crew")
        details = crew.get("farm_plot_details") if isinstance(crew, dict) else None
        if not isinstance(details, list):
            return set()
        observed: set[int] = set()
        for detail in details:
            if not isinstance(detail, dict) or detail.get("built") is not True:
                continue
            building_id = cls._positive_int(detail.get("id"))
            if building_id is not None:
                observed.add(building_id)
        return observed

    @staticmethod
    def _wait(intent: str) -> dict[str, Any]:
        return parse_action(
            {
                "type": "WAIT",
                "params": {},
                "intent": intent,
                "objective": "Allow the observed live precondition to become true.",
                "expected_simulation_result": (
                    "Existing governed jobs progress without a new command."
                ),
                "advance_ticks": P1_TICKS_PER_STEP,
            },
            max_advance_ticks=P1_TICKS_PER_STEP,
        )

    @classmethod
    def _interaction_recovery(
        cls, obs_text: str, obs_json: dict[str, Any]
    ) -> dict[str, Any] | None:
        if obs_json.get("pause_state") is not True:
            return None
        viewscreen = str(obs_json.get("viewscreen_type") or "unknown")
        if viewscreen not in INTERACT_ALLOWED_VIEWSCREEN_TYPES:
            return None
        if viewscreen == "viewscreen_topicmeetingst":
            if FINISH_TOPIC_MEETING_OPTION_TEXT in obs_text:
                operation = "finish_topic_meeting"
            elif visible_topic_meeting_option("topic_option_a", obs_text):
                operation = "topic_option_a"
            else:
                operation = "cancel"
        else:
            # Text notices close with LEAVESCREEN, and cancel is the only
            # non-selecting recovery for stores, requests, agreements, and
            # meeting submenus. A generic SELECT fallback can oscillate
            # forever between takerequests and stores.
            operation = "cancel"
        return parse_action(
            {
                "type": "INTERACT",
                "params": {"operation": operation},
                "intent": f"recover the observed {viewscreen} calibration modal",
                "objective": "Return to the live fortress map without advancing time.",
                "expected_visible_result": "The blocking interface advances or closes.",
                "advance_ticks": 0,
            },
            max_advance_ticks=P1_TICKS_PER_STEP,
        )

    def _remap_farm_action(
        self, action: dict[str, Any], obs_json: dict[str, Any]
    ) -> dict[str, Any] | None:
        params = action.get("params")
        historical_id = (
            self._positive_int(params.get("building_id"))
            if isinstance(params, dict)
            else None
        )
        if historical_id is None:
            return action
        actual_id = self._farm_id_map.get(historical_id)
        if actual_id is None:
            baseline = self._baseline_farm_ids or set()
            candidates = sorted(
                self._observed_farm_ids(obs_json)
                - baseline
                - self._assigned_farm_ids
            )
            if not candidates:
                return None
            actual_id = candidates[0]
            self._farm_id_map[historical_id] = actual_id
            self._assigned_farm_ids.add(actual_id)
        remapped = copy.deepcopy(action)
        remapped["params"]["building_id"] = actual_id
        return remapped

    def _bounded_precondition_wait(
        self, *, reason: str
    ) -> dict[str, Any] | None:
        key = (self._index, reason)
        waits = self._precondition_waits.get(key, 0)
        if waits >= self._MAX_PRECONDITION_WAITS:
            return None
        self._precondition_waits[key] = waits + 1
        return self._wait(reason)

    @classmethod
    def _available_furniture(
        cls, kind: str, obs_json: dict[str, Any]
    ) -> int:
        good = cls._FURNITURE_GOODS_BY_KIND.get(kind)
        crew = obs_json.get("crew")
        if good is None or not isinstance(crew, dict):
            return 0
        goods = crew.get("goods")
        placed = crew.get("placed_furniture")
        if not isinstance(goods, dict) or not isinstance(placed, dict):
            return 0
        produced = cls._positive_int(goods.get(good))
        installed = cls._positive_int(placed.get(good))
        if produced is None or installed is None:
            return 0
        return max(0, produced - installed)

    @classmethod
    def _brew_preconditions_observed(cls, obs_json: dict[str, Any]) -> bool:
        crew = obs_json.get("crew")
        if not isinstance(crew, dict):
            return False
        workshops = crew.get("workshops")
        inputs = crew.get("production_inputs")
        if not isinstance(workshops, list) or not isinstance(inputs, dict):
            return False
        built_still = any(
            isinstance(workshop, dict)
            and workshop.get("subtype") == "Still"
            and workshop.get("stage_read_ok") is True
            and workshop.get("built") is True
            for workshop in workshops
        )
        brewable = cls._positive_int(inputs.get("brewable_plant_stacks"))
        barrels = cls._positive_int(inputs.get("empty_barrels"))
        return bool(
            built_still
            and brewable is not None
            and brewable >= 1
            and barrels is not None
            and barrels >= 1
        )

    def decide(self, obs_text: str, obs_json: dict[str, Any]) -> dict[str, Any]:
        observed_farms = self._observed_farm_ids(obs_json)
        if self._baseline_farm_ids is None:
            self._baseline_farm_ids = observed_farms

        interaction = self._interaction_recovery(obs_text, obs_json)
        if interaction is not None:
            return interaction

        while self._index < len(self._actions):
            action = self._actions[self._index]
            if action.get("type") == "INTERACT":
                # The live calendar determines whether a meeting modal exists.
                # Scripted modal actions are audit placeholders, not blind keys.
                self._index += 1
                continue

            params = action.get("params")
            if action.get("type") == "ORDER" and isinstance(params, dict):
                job = str(params.get("job") or "").strip().casefold()
                work = obs_json.get("work")
                usable = (
                    self._positive_int(work.get("carpenter_workshops_usable"))
                    if isinstance(work, dict)
                    else 0
                )
                if job in self._CARPENTER_ORDER_JOBS and not usable:
                    wait = self._bounded_precondition_wait(
                        reason="wait for the observed carpenter workshop to become usable"
                    )
                    if wait is not None:
                        return wait
                if job == "brew" and not self._brew_preconditions_observed(obs_json):
                    wait = self._bounded_precondition_wait(
                        reason=(
                            "wait for a built Still, a brewable plant stack, "
                            "and an empty barrel"
                        )
                    )
                    if wait is not None:
                        return wait

            if action.get("type") == "BUILD" and isinstance(params, dict):
                kind = str(params.get("kind") or "")
                if (
                    kind in self._FURNITURE_GOODS_BY_KIND
                    and self._available_furniture(kind, obs_json) < 1
                ):
                    wait = self._bounded_precondition_wait(
                        reason=f"wait for an available produced {kind.lower()}"
                    )
                    if wait is not None:
                        return wait

            if action.get("type") == "FARM":
                remapped = self._remap_farm_action(action, obs_json)
                if remapped is None:
                    wait = self._bounded_precondition_wait(
                        reason="wait for the governed farm plot ID to become observable"
                    )
                    if wait is not None:
                        return wait
                else:
                    action = remapped

            self._index += 1
            return action
        return self._wait(
            "finish the controlled calibration observation window"
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
    actions = _load_plan(args.plan, scenario=args.scenario)
    run_id = run_once(
        CalibrationPlanAgent(actions),
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
        measurement_calibration_step_limit=len(actions),
    )
    print(run_id)


if __name__ == "__main__":
    main()
