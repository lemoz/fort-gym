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

## Your Objective
You are managing a dwarf fortress. **TAKE ACTION to improve the colony - don't just explore menus!**

IMPORTANT: The main menu (showing options like "d: Designations", "b: Building") is the NORMAL game view - it is NOT an overlay to close! To take actions, just press the corresponding key directly.

**DO SOMETHING CONSTRUCTIVE EACH TURN:**
1. **Dig more space**: D_DESIGNATE → DESIGNATE_DIG → select area with CURSOR + SELECT
2. **Build workshops/furniture**: D_BUILDJOB → select building type
3. **Create stockpiles**: D_STOCKPILES → define storage area

**DON'T waste turns just looking around.** Open a menu, then complete an action within it.

If you're unsure what to do, **ALWAYS dig**. Designate a small 3x3 mining area - it's always useful.

Use LEAVESCREEN only to exit SUB-menus (like after designating an area).

Tips:
- If Food/Drink is 0, the fortress is starving - dig for underground water/farms
- Mining creates space and resources - when in doubt, DIG MORE
- Don't check the same menu repeatedly - check once, then ACT

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

### Typing Letters (IMPORTANT!)
Many DF menus show options like "a - Do something". To select these, you must TYPE THE LETTER using STRING_A### format where ### is the ASCII code:
- STRING_A097 = 'a', STRING_A098 = 'b', STRING_A099 = 'c', STRING_A100 = 'd'
- STRING_A101 = 'e', STRING_A102 = 'f', STRING_A103 = 'g', STRING_A104 = 'h'
- STRING_A105 = 'i', STRING_A106 = 'j', STRING_A107 = 'k', STRING_A108 = 'l'
- STRING_A109 = 'm', STRING_A110 = 'n', STRING_A111 = 'o', STRING_A112 = 'p'
- STRING_A113 = 'q', STRING_A114 = 'r', STRING_A115 = 's', STRING_A116 = 't'
- STRING_A117 = 'u', STRING_A118 = 'v', STRING_A119 = 'w', STRING_A120 = 'x'
- STRING_A121 = 'y', STRING_A122 = 'z'

Example: If you see "a - Finish conversation", send STRING_A097 to press 'a'.

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

## Closing Popups and Notifications
Some popups say "Press Enter to close" but SELECT doesn't always work. If SELECT doesn't close a popup after 2-3 tries, try these alternatives:
- STANDARDSCROLL_PAGEDOWN - Often works for notification popups
- STRING_A032 (Space) - Sometimes needed to dismiss notifications
- LEAVESCREEN - Works for most dialogs and sub-menus

## Tips
- Look at the screen to understand current context/menu state
- If you see a menu with lettered options like "a - Something", use STRING_A### to type that letter
- If you see a dialog or popup, dismiss it first before trying other actions
- Start with simple actions like exploring or designating a small dig area
- Watch the screen feedback to see results of your actions
- **IMPORTANT**: If an action doesn't work after 2-3 tries, try a DIFFERENT key or approach. Don't repeat the same action endlessly."""


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
