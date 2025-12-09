"""Anthropic tool-use agent adapter."""

from __future__ import annotations

import json
import time
from importlib import import_module
from typing import Any, Dict, Optional

from .base import Agent, register_agent
from ..config import get_settings
from ..env.actions import ACTION_TOOL_SPEC, parse_action, system_prompt_v1


ANTHROPIC_TOOL = {
    "name": ACTION_TOOL_SPEC["name"],
    "description": ACTION_TOOL_SPEC["description"],
    "input_schema": ACTION_TOOL_SPEC["parameters"],
}


# Keystroke mode system prompt
KEYSTROKE_SYSTEM_PROMPT = """You are playing Dwarf Fortress. You control the game by sending keystrokes.

## Screen
You see the current game screen as text (80 columns x 25 rows). The screen shows the DF interface including menus, the map view, and status information.

## Actions
Return a KEYSTROKE action with a list of key names to press in sequence.

## Key Reference

### Navigation
- CURSOR_UP, CURSOR_DOWN, CURSOR_LEFT, CURSOR_RIGHT - Move cursor 1 tile
- CURSOR_UP_FAST, CURSOR_DOWN_FAST, etc. - Move cursor 10 tiles
- CURSOR_UP_Z, CURSOR_DOWN_Z - Move up/down z-levels

### Selection
- SELECT - Confirm/Enter
- LEAVESCREEN - Cancel/Escape
- DESELECT - Clear selection

### Main Menus (press from main view)
- D_DESIGNATE - Open designate menu (d key)
- D_BUILDJOB - Open build menu (b key)
- D_STOCKPILES - Open stockpiles menu (p key)
- D_ZONES - Open zones menu (i key)
- D_ORDERS - Open standing orders (o key)

### Designate Submenu (after D_DESIGNATE)
- DESIGNATE_DIG - Mine/dig mode (d key)
- DESIGNATE_CHANNEL - Channel mode (h key)
- DESIGNATE_STAIR_DOWN - Downward staircase (j key)
- DESIGNATE_STAIR_UP - Upward staircase (u key)
- DESIGNATE_RAMP - Ramp (r key)
- DESIGNATE_CHOP - Chop trees (t key)

## How to Dig
1. Press D_DESIGNATE to open designate menu
2. Press DESIGNATE_DIG to select dig mode
3. Use CURSOR keys to navigate to start position
4. Press SELECT to mark first corner
5. Use CURSOR keys to move to end position
6. Press SELECT to mark second corner and complete
7. Press LEAVESCREEN to exit menu

## Response Format
Always return exactly one action:
{
  "type": "KEYSTROKE",
  "params": {"keys": ["KEY1", "KEY2", ...]},
  "intent": "Brief description of what you're trying to do"
}

## Tips
- Look at the screen to understand current context/menu state
- If you see a menu, navigate it appropriately
- Start with simple actions like exploring or designating a small dig area
- Watch the screen feedback to see results of your actions"""


KEYSTROKE_TOOL_SPEC = {
    "name": "submit_action",
    "description": "Submit a keystroke sequence to control Dwarf Fortress",
    "parameters": {
        "type": "object",
        "properties": {
            "type": {
                "type": "string",
                "const": "KEYSTROKE",
            },
            "params": {
                "type": "object",
                "properties": {
                    "keys": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of interface_key names to send",
                    },
                },
                "required": ["keys"],
            },
            "intent": {
                "type": "string",
                "description": "Brief description of what this action accomplishes",
            },
        },
        "required": ["type", "params", "intent"],
    },
}

KEYSTROKE_ANTHROPIC_TOOL = {
    "name": KEYSTROKE_TOOL_SPEC["name"],
    "description": KEYSTROKE_TOOL_SPEC["description"],
    "input_schema": KEYSTROKE_TOOL_SPEC["parameters"],
}


class AnthropicActionAgent(Agent):
    """Calls Anthropic Messages API with tool-use for submit_action."""

    def __init__(self) -> None:
        self._settings = get_settings()
        if not self._settings.ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY not configured")
        self._client = None
        self._last_call = 0.0

    def _rate_limit(self) -> None:
        limit = self._settings.LLM_RATE_LIMIT_TPS
        if limit <= 0:
            return
        interval = 1.0 / limit
        now = time.monotonic()
        wait = interval - (now - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _client_instance(self):
        if self._client is None:
            try:
                anthropic_mod = import_module("anthropic")
            except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
                raise RuntimeError("anthropic package not installed") from exc
            client_cls = getattr(anthropic_mod, "Anthropic", None)
            if client_cls is None:
                raise RuntimeError("anthropic.Anthropic client not available")
            self._client = client_cls(api_key=self._settings.ANTHROPIC_API_KEY)
        return self._client

    def decide(self, obs_text: str, obs_json: Dict[str, Any]) -> Dict[str, Any]:
        content = f"{obs_text}\n\nState JSON:\n{json.dumps(obs_json)}"
        last_error: Optional[Exception] = None

        for _ in range(3):
            self._rate_limit()
            client = self._client_instance()
            response = client.messages.create(
                model=self._settings.ANTHROPIC_MODEL,
                max_tokens=self._settings.LLM_MAX_TOKENS,
                temperature=self._settings.LLM_TEMP,
                system=system_prompt_v1,
                tools=[ANTHROPIC_TOOL],
                messages=[
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": content}],
                    }
                ],
            )

            tool_payload = None
            for item in response.content:
                if item.type == "tool_use" and item.name == ACTION_TOOL_SPEC["name"]:
                    tool_payload = item.input
                    break
            if tool_payload is None:
                last_error = ValueError("Model did not use submit_action tool")
                continue
            try:
                return parse_action(tool_payload)
            except ValueError as exc:
                last_error = exc
                content += f"\n\nPrevious response invalid ({exc}). Provide one action."

        raise RuntimeError(f"Anthropic agent failed to produce action: {last_error}")


register_agent("anthropic", lambda: AnthropicActionAgent())


class AnthropicKeystrokeAgent(Agent):
    """Anthropic agent for keystroke-based game control."""

    def __init__(self) -> None:
        self._settings = get_settings()
        if not self._settings.ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY not configured")
        self._client = None
        self._last_call = 0.0

    def _rate_limit(self) -> None:
        limit = self._settings.LLM_RATE_LIMIT_TPS
        if limit <= 0:
            return
        interval = 1.0 / limit
        now = time.monotonic()
        wait = interval - (now - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _client_instance(self):
        if self._client is None:
            try:
                anthropic_mod = import_module("anthropic")
            except ModuleNotFoundError as exc:
                raise RuntimeError("anthropic package not installed") from exc
            client_cls = getattr(anthropic_mod, "Anthropic", None)
            if client_cls is None:
                raise RuntimeError("anthropic.Anthropic client not available")
            self._client = client_cls(api_key=self._settings.ANTHROPIC_API_KEY)
        return self._client

    def decide(self, obs_text: str, obs_json: Dict[str, Any]) -> Dict[str, Any]:
        """Decide on a keystroke action based on screen observation."""
        # For keystroke mode, obs_text already contains screen + status
        # We don't need to include full JSON state since screen is the primary input
        content = obs_text
        last_error: Optional[Exception] = None

        for attempt in range(3):
            self._rate_limit()
            client = self._client_instance()
            response = client.messages.create(
                model=self._settings.ANTHROPIC_MODEL,
                max_tokens=self._settings.LLM_MAX_TOKENS,
                temperature=self._settings.LLM_TEMP,
                system=KEYSTROKE_SYSTEM_PROMPT,
                tools=[KEYSTROKE_ANTHROPIC_TOOL],
                messages=[
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": content}],
                    }
                ],
            )

            tool_payload = None
            for item in response.content:
                if item.type == "tool_use" and item.name == "submit_action":
                    tool_payload = item.input
                    break

            if tool_payload is None:
                last_error = ValueError("Model did not use submit_action tool")
                continue

            # Validate it's a KEYSTROKE action
            if tool_payload.get("type") != "KEYSTROKE":
                last_error = ValueError(f"Expected KEYSTROKE action, got {tool_payload.get('type')}")
                content += f"\n\nYou must return a KEYSTROKE action. Try again."
                continue

            params = tool_payload.get("params", {})
            keys = params.get("keys", [])
            if not keys or not isinstance(keys, list):
                last_error = ValueError("KEYSTROKE action must have non-empty keys list")
                content += f"\n\nKEYSTROKE action requires a non-empty keys list. Try again."
                continue

            try:
                return parse_action(tool_payload)
            except ValueError as exc:
                last_error = exc
                content += f"\n\nPrevious response invalid ({exc}). Provide valid KEYSTROKE action."

        raise RuntimeError(f"Anthropic keystroke agent failed: {last_error}")


register_agent("anthropic-keystroke", lambda: AnthropicKeystrokeAgent())


__all__ = ["AnthropicActionAgent", "AnthropicKeystrokeAgent"]
