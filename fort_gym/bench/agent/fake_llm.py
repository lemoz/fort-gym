"""Deterministic agent used for tests and development."""

from __future__ import annotations

import json
from typing import Any, Dict

from .base import Agent, register_agent
from ..env.actions import parse_action


class FakeLLMAgent(Agent):
    """Always emits a small DIG action for predictable tests."""

    def decide(self, obs_text: str, obs_json: Dict[str, Any]) -> Dict[str, Any]:
        action = {
            "type": "DIG",
            "params": {"area": [0, 0, 0], "size": [1, 1, 1]},
            "intent": "fake agent baseline",
        }
        return parse_action(action)


register_agent("fake", lambda: FakeLLMAgent())


__all__ = ["FakeLLMAgent"]
