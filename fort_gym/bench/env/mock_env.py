"""Deterministic mock environment for fort-gym development and testing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import random

from .scenarios import MockScenario, get_mock_scenario


@dataclass
class MockEnvironment:
    """Simple deterministic environment emulating fortress state transitions."""

    seed: int = 123
    time: int = 0
    population: int = 7
    stocks: Dict[str, int] = field(default_factory=lambda: {"food": 100, "drink": 80})
    risks: List[str] = field(default_factory=list)
    reminders: List[str] = field(default_factory=list)
    recent_events: List[str] = field(default_factory=list)
    scenario_name: Optional[str] = None
    target_dig_designations: int = 0
    target_floor_tiles: int = 0
    target_wall_tiles: int = 25
    active_dig_jobs: int = 0
    rng: random.Random = field(init=False)

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)

    def reset(self, seed: Optional[int] = None, scenario_name: Optional[str] = None) -> None:
        """Reset environment to deterministic seed."""

        if seed is not None:
            self.seed = seed
        if scenario_name is not None:
            self.scenario_name = scenario_name
        self.rng.seed(self.seed)
        self.time = 0
        self.population = 7
        self.stocks = {"food": 100, "drink": 80}
        self.risks = []
        self.reminders = []
        self.recent_events = []
        self.target_dig_designations = 0
        self.target_floor_tiles = 0
        self.target_wall_tiles = 25
        self.active_dig_jobs = 0
        if self.scenario_name:
            self._apply_scenario(get_mock_scenario(self.scenario_name))

    def _apply_scenario(self, scenario: MockScenario) -> None:
        initial = scenario.initial_state
        if "time" in initial:
            self.time = int(initial["time"])
        if "population" in initial:
            self.population = int(initial["population"])
        if isinstance(initial.get("stocks"), dict):
            self.stocks.update(initial["stocks"])
        if isinstance(initial.get("risks"), list):
            self.risks = [str(item) for item in initial["risks"]]
        if isinstance(initial.get("reminders"), list):
            self.reminders = [str(item) for item in initial["reminders"]]
        self.recent_events.append(f"Scenario loaded: {scenario.name}")

    def observe(self) -> Dict[str, Any]:
        """Return current observable state."""

        return {
            "time": self.time,
            "population": self.population,
            "stocks": dict(self.stocks),
            "risks": list(self.risks),
            "reminders": list(self.reminders),
            "recent_events": list(self.recent_events[-5:]),
            "scenario": self.scenario_name,
            "dwarves": [
                {"name": f"Dwarf {i+1}", "mood": "content"}
                for i in range(self.population)
            ],
            "map_bounds": (200, 200, 50),
            "workshops": {"CarpenterWorkshop": 0},
            "work": {
                "ok": True,
                "target_rect": [50, 35, 0, 54, 39, 0],
                "target_tiles": 25,
                "target_dig_designations": self.target_dig_designations,
                "target_floor_tiles": self.target_floor_tiles,
                "target_wall_tiles": self.target_wall_tiles,
                "active_jobs": self.active_dig_jobs,
                "active_dig_jobs": self.active_dig_jobs,
            },
        }

    def apply(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Apply action with deterministic bookkeeping."""

        action_type = action.get("type")
        params = action.get("params", {})
        summary = f"{action_type}: {params}"
        self.recent_events.append(summary)

        if action_type == "DIG":
            self.stocks["food"] = max(0, self.stocks["food"] - 1)
            area = params.get("area") or params.get("location") or []
            size = params.get("size") or [1, 1, 1]
            if list(area)[:3] == [50, 35, 0]:
                self.target_dig_designations = min(25, int(size[0]) * int(size[1]))
                self.active_dig_jobs = 1
        elif action_type == "BUILD":
            self.stocks["drink"] = max(0, self.stocks["drink"] - 1)
        elif action_type == "ORDER":
            quantity = params.get("quantity", 0)
            self.reminders.append(f"Order queued: {params.get('job', 'unknown')} x{quantity}")
        elif action_type == "ALERT":
            self.risks.append(params.get("message", "alert raised"))
        elif action_type == "NOTE":
            self.reminders.append(params.get("text", "note"))

        return self.observe()

    def advance(self, ticks: int) -> Dict[str, Any]:
        """Advance simulation clock and degrade stocks slightly."""

        self.time += ticks
        food_loss = ticks // 50
        drink_loss = ticks // 60
        self.stocks["food"] = max(0, self.stocks["food"] - food_loss)
        self.stocks["drink"] = max(0, self.stocks["drink"] - drink_loss)
        if self.target_dig_designations and ticks > 0:
            mined = min(self.target_dig_designations, max(1, ticks // 200))
            self.target_dig_designations -= mined
            self.target_floor_tiles = min(25, self.target_floor_tiles + mined)
            self.target_wall_tiles = max(0, self.target_wall_tiles - mined)
            if self.target_dig_designations == 0:
                self.active_dig_jobs = 0

        # Deterministic population changes for demonstration
        if self.time and self.time % 1000 == 0:
            self.population += 1
            self.recent_events.append("Migrant arrived")

        return self.observe()
