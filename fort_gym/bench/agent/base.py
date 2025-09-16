"""Agent interfaces and simple random baseline."""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List

from ..env.actions import ALLOWED_TYPES, parse_action


class Agent(ABC):
    """Base agent contract for fort-gym."""

    @abstractmethod
    def decide(self, obs_text: str, obs_json: Dict[str, Any]) -> Dict[str, Any]:
        """Return exactly one action dict based on the observation."""


class RandomAgent(Agent):
    """Random policy emitting syntactically valid actions."""

    def __init__(self, seed: int = 0) -> None:
        self._rng = random.Random(seed)

    def decide(self, obs_text: str, obs_json: Dict[str, Any]) -> Dict[str, Any]:
        action_type = self._rng.choice(sorted(ALLOWED_TYPES))
        params: Dict[str, Any]
        if action_type == "DIG":
            params = {
                "area": (0, 0, 0),
                "size": (3, 3, 1),
            }
        elif action_type == "BUILD":
            params = {
                "kind": "CarpenterWorkshop",
                "x": 1,
                "y": 1,
                "z": 0,
            }
        elif action_type == "ORDER":
            params = {
                "job": "brew_drink",
                "quantity": 5,
            }
        else:
            params = {}

        action = {"type": action_type, "params": params, "intent": "random baseline"}
        # Ensure schema compliance by round-tripping through parser
        return parse_action(action)


AGENT_FACTORIES: Dict[str, Callable[[], Agent]] = {
    "random": lambda: RandomAgent(),
}


def register_agent(name: str, factory: Callable[[], Agent]) -> None:
    AGENT_FACTORIES[name] = factory


__all__ = ["Agent", "RandomAgent", "AGENT_FACTORIES", "register_agent"]
