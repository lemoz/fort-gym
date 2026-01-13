"""Agent interfaces and simple random baseline."""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List

from ..env.actions import ALLOWED_TYPES, parse_action
from ..dfhack_backend import ALLOWED_ITEMS


class Agent(ABC):
    """Base agent contract for fort-gym."""

    @abstractmethod
    def decide(self, obs_text: str, obs_json: Dict[str, Any]) -> Dict[str, Any]:
        """Return exactly one action dict based on the observation."""

    def pop_tool_events(self) -> List[Dict[str, Any]]:
        """Return tool-call events emitted during the last decision step."""
        return []


class RandomAgent(Agent):
    """Random policy emitting syntactically valid actions."""

    def __init__(self, seed: int = 0, safe: bool = True) -> None:
        self._rng = random.Random(seed)
        self._safe = safe

    def set_safe(self, value: bool) -> None:
        self._safe = value

    def decide(self, obs_text: str, obs_json: Dict[str, Any]) -> Dict[str, Any]:
        if not self._safe:
            action_type = self._rng.choice(sorted(ALLOWED_TYPES))
            params: Dict[str, Any]
            if action_type == "DIG":
                params = {"area": (0, 0, 0), "size": (3, 3, 1)}
            elif action_type == "BUILD":
                params = {"kind": "CarpenterWorkshop", "x": 1, "y": 1, "z": 0}
            elif action_type == "ORDER":
                params = {"job": "brew_drink", "quantity": 5}
            else:
                params = {}
            action = {"type": action_type, "params": params, "intent": "random baseline"}
            return parse_action(action)

        choices = ["noop", "dig", "order"]
        action_kind = self._rng.choice(choices)
        params: Dict[str, Any]
        if action_kind == "dig":
            x = self._rng.randint(0, 20)
            y = self._rng.randint(0, 20)
            params = {
                "area": (x, y, 0),
                "size": (self._rng.randint(1, 5), self._rng.randint(1, 5), 1),
            }
            action = {"type": "DIG", "params": params, "intent": "random baseline"}
            return parse_action(action)

        if action_kind == "order":
            item = self._rng.choice(sorted(ALLOWED_ITEMS))
            qty = self._rng.randint(1, 2)
            params = {"job": item, "quantity": qty}
            action = {"type": "ORDER", "params": params, "intent": "random baseline"}
            return parse_action(action)

        # noop fallback
        return {"type": "noop", "params": {}, "intent": "random baseline"}


AGENT_FACTORIES: Dict[str, Callable[[], Agent]] = {
    "random": lambda: RandomAgent(),
}


def register_agent(name: str, factory: Callable[[], Agent]) -> None:
    AGENT_FACTORIES[name] = factory


__all__ = ["Agent", "RandomAgent", "AGENT_FACTORIES", "register_agent"]
