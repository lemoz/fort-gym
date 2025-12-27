"""Anthropic agent with web research capability for learning DF gameplay."""

from __future__ import annotations

import json
import time
import urllib.request
import urllib.parse
from importlib import import_module
from typing import Any, Dict, List, Optional

from .base import Agent, register_agent
from ..config import get_settings
from ..env.actions import parse_action


# Enhanced system prompt with DF knowledge
RESEARCH_KEYSTROKE_PROMPT = """You are playing Dwarf Fortress. You control the game by sending keystrokes.

## Your Objective
Manage a thriving dwarf fortress. You start with 7 dwarves on an embark site.

## CRITICAL: Understanding the Screen Layout

The screen is divided into THREE COLUMNS (left to right):

### COLUMN 1 (LEFT ~25 chars): LOCAL MAP
This is YOUR view - where your cursor is and where you designate actions!
- Shows ~25 character wide area of terrain
- Your cursor appears as `X` (yellow) - THIS IS WHERE YOU'RE POINTING

**IMPORTANT: The `#` at the very START of each line is a SCREEN BORDER, not stone!**
Look INSIDE the map area for terrain:
- Terrain symbols INSIDE the map:
  - `τ` `f` `"` `O` = Trees and plants (surface forest - NOT mineable!)
  - `.` `,` `'` = Grass/ground (surface - NOT mineable!)
  - `#` INSIDE the map (not at edges) = STONE WALL - this IS mineable!
  - `≈` `~` = Water
  - `@` or colored letters = Dwarves
- The LOCAL MAP scrolls as you move the cursor

**If you only see trees/grass in the local map, the stone is UNDERGROUND!**
- Use CURSOR_DOWN_Z to go DOWN one z-level
- Keep going down until you see `#` stone tiles INSIDE the map
- Mountain embark sites have stone 1-3 z-levels below the surface

### COLUMN 2 (MIDDLE ~35 chars): MENU
Shows current menu options and commands:
- Main menu: "d: Designations", "b: Building", etc.
- Submenus: "d: Mine", "h: Channel", etc.
- Status info like "Selection: 3x3x1"
- This tells you WHAT COMMANDS ARE AVAILABLE

### COLUMN 3 (RIGHT ~20 chars): REGIONAL MAP
A zoomed-out overview showing the whole embark area:
- Green `↑` arrows = Trees/forest
- Blue areas = Water/rivers
- Gray/brown = Mountains/stone (your target!)
- Shows where you are in the bigger picture
- The cursor position is also shown here

## KEY INSIGHT: Focus on COLUMN 1 (LOCAL MAP)
When navigating, watch the LEFT column to see:
1. Where your X cursor is
2. What terrain is around it
3. Whether you're on grass (bad for mining) or near stone (good!)

The gray/brown area in the REGIONAL MAP (right) = mountains = where you want to dig!

## STRATEGY: What You Should Actually Do

### First Priority: FIND STONE (it's usually underground!)
1. Look at LOCAL MAP - if you only see trees (`τ` `f` `O`) and grass (`. , '`), stone is BELOW you
2. Press CURSOR_DOWN_Z to go down one z-level (this is the `>` key motion)
3. Keep going down until you see `#` stone tiles INSIDE the local map
4. Once you see stone `#`, THEN open Designate → Mine

### How to Dig Once You Find Stone:
1. Open Designate menu: D_DESIGNATE
2. Select Mine: DESIGNATE_DIG (or press 'd')
3. Move cursor to a `#` stone tile
4. Press SELECT to mark first corner
5. Move cursor to expand selection (3x5 tiles is good)
6. Press SELECT again to confirm
7. Press LEAVESCREEN to exit menu
8. Advance time (advance_ticks: 500) to let dwarves dig

### How to Know You're in the Right Place:
- LOCAL MAP shows `#` symbols INSIDE (not at edges) = You found stone! Mine here!
- If you only see `τ` `f` `.` `O` = You're on surface, GO DOWN (CURSOR_DOWN_Z)
- The STATUS will show "Selection: 3x5x1" when you're designating an area

### Common Mistakes to Avoid:
- DON'T try to mine where you only see trees/grass - move to find stone first!
- DON'T ignore the screen feedback - if cursor didn't move, try different keys
- DON'T just repeat failed actions - change your approach!

## Using the Research Tool
You have a `web_search` tool. Use it when stuck to look up guides.

## Key Reference

### Navigation
- CURSOR_UP, CURSOR_DOWN, CURSOR_LEFT, CURSOR_RIGHT - Move cursor 1 tile
- CURSOR_UP_FAST, CURSOR_DOWN_FAST, etc. - Move cursor 10 tiles
- CURSOR_UP_Z, CURSOR_DOWN_Z - Move up/down z-levels

### Selection
- SELECT - Confirm/Enter
- LEAVESCREEN - Cancel/Escape

### Typing Letters
Menu options like "a - Do something" need STRING_A### format:
- STRING_A097 = 'a', STRING_A098 = 'b', STRING_A099 = 'c', STRING_A100 = 'd'
- STRING_A101 = 'e', STRING_A102 = 'f', STRING_A103 = 'g', STRING_A104 = 'h'
- STRING_A105 = 'i', STRING_A106 = 'j', STRING_A107 = 'k', STRING_A108 = 'l'
- STRING_A109 = 'm', STRING_A110 = 'n', STRING_A111 = 'o', STRING_A112 = 'p'

### Main Menus
- D_DESIGNATE - Designations menu (d key)
- D_BUILDJOB - Build menu (b key)
- D_STOCKPILES - Stockpiles menu (p key)
- STRING_A107 - Look mode (k key)

### Designate Submenu
- DESIGNATE_DIG - Mine/dig mode (d key)
- DESIGNATE_CHANNEL - Channel mode (h key)
- DESIGNATE_CHOP - Chop trees (t key)

## Response Format
Return exactly one action:
{
  "type": "KEYSTROKE",
  "params": {"keys": ["KEY1", "KEY2", ...]},
  "intent": "What you're trying to accomplish",
  "advance_ticks": 200
}

## Time Control
- advance_ticks: 0 - Menu navigation (instant)
- advance_ticks: 100-500 - Let dwarves work after designating"""


WEB_SEARCH_TOOL = {
    "name": "web_search",
    "description": "Search the web for Dwarf Fortress guides and tutorials. Use this when you need help understanding the game.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query, e.g. 'dwarf fortress how to dig into mountain'"
            }
        },
        "required": ["query"]
    }
}

KEYSTROKE_TOOL = {
    "name": "submit_action",
    "description": "Submit a keystroke sequence to control Dwarf Fortress",
    "input_schema": {
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
            "advance_ticks": {
                "type": "integer",
                "minimum": 0,
                "maximum": 2000,
                "default": 0,
                "description": "Game ticks to advance after keystrokes. 0 = stay paused.",
            },
        },
        "required": ["type", "params", "intent"],
    },
}


def _do_web_search(query: str) -> str:
    """Perform a simple web search using DuckDuckGo HTML."""
    try:
        # Use DuckDuckGo HTML version for simplicity
        encoded_query = urllib.parse.quote(f"dwarf fortress {query}")
        url = f"https://html.duckduckgo.com/html/?q={encoded_query}"

        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; DFAgent/1.0)"}
        )

        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode("utf-8", errors="ignore")

        # Extract text snippets from results (basic parsing)
        results = []
        import re
        # Find result snippets
        snippets = re.findall(r'class="result__snippet"[^>]*>([^<]+)', html)
        for i, snippet in enumerate(snippets[:5]):  # Top 5 results
            clean = snippet.strip()
            if clean:
                results.append(f"{i+1}. {clean}")

        if results:
            return "Search results:\n" + "\n".join(results)
        return "No results found. Try a different search."

    except Exception as e:
        return f"Search failed: {e}. Proceed with your best judgment."


class AnthropicResearchAgent(Agent):
    """Anthropic keystroke agent with web research capability."""

    def __init__(self) -> None:
        self._settings = get_settings()
        if not self._settings.ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY not configured")
        self._client = None
        self._last_call = 0.0
        self._search_cache: Dict[str, str] = {}

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

    def _handle_tool_use(self, tool_name: str, tool_input: Dict[str, Any]) -> str:
        """Handle tool calls from the model."""
        if tool_name == "web_search":
            query = tool_input.get("query", "")
            # Check cache first
            if query in self._search_cache:
                return self._search_cache[query]
            result = _do_web_search(query)
            self._search_cache[query] = result
            return result
        return f"Unknown tool: {tool_name}"

    def decide(self, obs_text: str, obs_json: Dict[str, Any]) -> Dict[str, Any]:
        """Decide on action, potentially using web search first."""
        content = obs_text
        messages: List[Dict[str, Any]] = [
            {"role": "user", "content": [{"type": "text", "text": content}]}
        ]

        last_error: Optional[Exception] = None
        tools = [WEB_SEARCH_TOOL, KEYSTROKE_TOOL]

        for attempt in range(5):  # More attempts since we may have tool calls
            self._rate_limit()
            client = self._client_instance()

            response = client.messages.create(
                model=self._settings.ANTHROPIC_MODEL,
                max_tokens=self._settings.LLM_MAX_TOKENS,
                temperature=self._settings.LLM_TEMP,
                system=RESEARCH_KEYSTROKE_PROMPT,
                tools=tools,
                messages=messages,
            )

            # Check for tool use
            action_payload = None
            tool_uses = []

            for item in response.content:
                if item.type == "tool_use":
                    if item.name == "submit_action":
                        action_payload = item.input
                    else:
                        tool_uses.append(item)

            # If we got an action, validate and return it
            if action_payload is not None:
                if action_payload.get("type") != "KEYSTROKE":
                    last_error = ValueError(f"Expected KEYSTROKE, got {action_payload.get('type')}")
                    messages.append({"role": "assistant", "content": response.content})
                    messages.append({
                        "role": "user",
                        "content": [{"type": "text", "text": "You must return a KEYSTROKE action."}]
                    })
                    continue

                params = action_payload.get("params", {})
                keys = params.get("keys", [])
                if not keys or not isinstance(keys, list):
                    last_error = ValueError("KEYSTROKE requires non-empty keys list")
                    messages.append({"role": "assistant", "content": response.content})
                    messages.append({
                        "role": "user",
                        "content": [{"type": "text", "text": "KEYSTROKE action requires a non-empty keys list."}]
                    })
                    continue

                try:
                    return parse_action(action_payload)
                except ValueError as exc:
                    last_error = exc
                    messages.append({"role": "assistant", "content": response.content})
                    messages.append({
                        "role": "user",
                        "content": [{"type": "text", "text": f"Invalid action ({exc}). Try again."}]
                    })
                    continue

            # Handle other tool calls (like web_search)
            if tool_uses:
                # Add assistant response to messages
                messages.append({"role": "assistant", "content": response.content})

                # Process each tool call
                tool_results = []
                for tool_use in tool_uses:
                    result = self._handle_tool_use(tool_use.name, tool_use.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": result,
                    })

                # Add tool results
                messages.append({"role": "user", "content": tool_results})
                continue

            # No action and no tool calls - ask for action
            last_error = ValueError("Model did not return an action")
            messages.append({"role": "assistant", "content": response.content})
            messages.append({
                "role": "user",
                "content": [{"type": "text", "text": "Please use the submit_action tool to send keystrokes."}]
            })

        raise RuntimeError(f"Research agent failed: {last_error}")


register_agent("anthropic-research", lambda: AnthropicResearchAgent())


__all__ = ["AnthropicResearchAgent"]
