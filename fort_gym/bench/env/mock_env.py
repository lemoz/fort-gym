"""Deterministic mock environment for fort-gym development and testing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import random


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
    rng: random.Random = field(init=False)

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)

    def reset(self, seed: Optional[int] = None) -> None:
        """Reset environment to deterministic seed."""

        if seed is not None:
            self.seed = seed
        self.rng.seed(self.seed)
        self.time = 0
        self.population = 7
        self.stocks = {"food": 100, "drink": 80}
        self.risks = []
        self.reminders = []
        self.recent_events = []

    def observe(self) -> Dict[str, Any]:
        """Return current observable state."""

        return {
            "time": self.time,
            "population": self.population,
            "stocks": dict(self.stocks),
            "risks": list(self.risks),
            "reminders": list(self.reminders),
            "recent_events": list(self.recent_events[-5:]),
            "dwarves": [
                {"name": f"Dwarf {i+1}", "mood": "content"}
                for i in range(self.population)
            ],
            "map_bounds": (200, 200, 50),
            "workshops": {"CarpenterWorkshop": 0},
        }

    def apply(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Apply action with deterministic bookkeeping."""

        action_type = action.get("type")
        params = action.get("params", {})
        summary = f"{action_type}: {params}"
        self.recent_events.append(summary)

        if action_type == "DIG":
            self.stocks["food"] = max(0, self.stocks["food"] - 1)
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

        # Deterministic population changes for demonstration
        if self.time and self.time % 1000 == 0:
            self.population += 1
            self.recent_events.append("Migrant arrived")

        return self.observe()
