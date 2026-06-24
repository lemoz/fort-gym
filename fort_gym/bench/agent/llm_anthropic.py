"""Anthropic tool-use agent adapter."""

from __future__ import annotations

import json
import os
import re
import time
from importlib import import_module
from typing import Any, Dict, List, Optional

from .base import Agent, register_agent
from .memory import MemoryManager
from .tools import ToolManager
from ..config import get_settings
from ..env.actions import ACTION_TOOL_SPEC, parse_action, system_prompt_v1


ANTHROPIC_TOOL = {
    "name": ACTION_TOOL_SPEC["name"],
    "description": ACTION_TOOL_SPEC["description"],
    "input_schema": ACTION_TOOL_SPEC["parameters"],
}


DIG_FIRST_SYSTEM_PROMPT = """You are the fortress overseer. One action per step. Never return multiple actions or plans.

Use fort-gym's structured action API. Do not drive the Dwarf Fortress UI with keystrokes.

Your priority is to create useful underground workspace, then start useful fortress work:
1. First action: emit a DIG action with area [50, 35, 0], size [5, 5, 1], and advance_ticks 500.
2. Read work metrics literally: target_dig_designations == 0 means no dig has been designated yet.
3. target_wall_tiles > 0 means the target is still solid wall and should be mined, not treated as completed work.
4. target_floor_tiles >= 25 or target_wall_tiles == 0 means the starter room is complete.
5. After the room is complete, emit an ORDER action for bed quantity 5 unless manager_orders_count or manager_orders_amount_left already increased.
6. After manager_orders_count or manager_orders_amount_left increased, emit a BUILD action for CarpenterWorkshop at x=51, y=36, z=0 unless carpenter_workshops already increased.
7. After carpenter_workshops increased, WAIT with advance_ticks 200 so the trace records stable production progress.

Examples:
- DIG: {"type":"DIG","params":{"area":[50,35,0],"size":[5,5,1]},"intent":"designate a starter room","advance_ticks":500}
- WAIT: {"type":"WAIT","params":{},"intent":"let miners work","advance_ticks":500}
- ORDER: {"type":"ORDER","params":{"job":"bed","quantity":5},"intent":"queue beds after the starter room is complete","advance_ticks":200}
- BUILD: {"type":"BUILD","params":{"kind":"CarpenterWorkshop","x":51,"y":36,"z":0},"intent":"place a carpenter workshop in the completed starter room","advance_ticks":200}

The harness executes DIG, safe ORDER actions, and bounded CarpenterWorkshop BUILD actions directly through DFHack, so structured actions are more reliable than opening menus.
Return exactly one submit_action tool call."""


FORTRESS_PLAN_SYSTEM_PROMPT = """You are the fortress overseer. One action per step. Never return multiple actions or plans.

Use fort-gym's structured action API. Do not drive the Dwarf Fortress UI with keystrokes.

Your objective is to create a visible, purposeful two-room fortress plan, not just a single starter room:
1. Dig the starter room first: DIG area [50, 35, 0], size [5, 5, 1], advance_ticks 500.
2. When target_floor_tiles >= 25 or target_wall_tiles == 0, dig the connector hallway: DIG area [55, 37, 0], size [3, 1, 1], advance_ticks 250.
3. When fortress_connector_floor_tiles >= 3, dig the workshop room: DIG area [58, 35, 0], size [5, 5, 1], advance_ticks 500.
4. When fortress_workshop_room_floor_tiles >= 25, queue useful work: ORDER bed quantity 5 unless manager_orders_count or manager_orders_amount_left already increased.
5. After the order exists, place production in the workshop room: BUILD CarpenterWorkshop at x=59, y=36, z=0 unless carpenter_workshops already increased.
6. After the workshop exists, WAIT with advance_ticks 200 so the public trace records stable fortress complexity and production progress.

Read work metrics literally:
- target_floor_tiles tracks the starter room.
- fortress_connector_floor_tiles tracks the east connector hallway; 3 means complete.
- fortress_workshop_room_floor_tiles tracks the second 5x5 workshop room; 25 means complete.
- fortress_complexity_spaces_completed reaches 2 when the connector and workshop room are both visibly opened.

Examples:
- DIG starter: {"type":"DIG","params":{"area":[50,35,0],"size":[5,5,1]},"intent":"carve the first room of the fortress plan","advance_ticks":500}
- DIG connector: {"type":"DIG","params":{"area":[55,37,0],"size":[3,1,1]},"intent":"connect the starter room to the workshop annex","advance_ticks":250}
- DIG workshop room: {"type":"DIG","params":{"area":[58,35,0],"size":[5,5,1]},"intent":"carve a dedicated workshop room east of the starter room","advance_ticks":500}
- ORDER: {"type":"ORDER","params":{"job":"bed","quantity":5},"intent":"queue useful furniture work after the rooms exist","advance_ticks":200}
- BUILD: {"type":"BUILD","params":{"kind":"CarpenterWorkshop","x":59,"y":36,"z":0},"intent":"place production in the dedicated workshop room","advance_ticks":200}
- WAIT: {"type":"WAIT","params":{},"intent":"let the completed two-room fortress plan stabilize in the trace","advance_ticks":200}

Return exactly one submit_action tool call."""


# Keystroke mode system prompt
KEYSTROKE_SYSTEM_PROMPT = """You are playing Dwarf Fortress. You control the game by sending keystrokes.

## Your Objective
You are managing a dwarf fortress. **TAKE ACTION to improve the colony - don't just explore menus!**

IMPORTANT: The main menu (showing options like "d: Designations", "b: Building") is the NORMAL game view - it is NOT an overlay to close! To take actions, just press the corresponding key directly.

**DO SOMETHING CONSTRUCTIVE EACH TURN:**
1. **Dig more space**: D_DESIGNATE → DESIGNATE_DIG → select area with CURSOR + SELECT
2. **Build workshops/furniture**: D_BUILDING → select building type
3. **Create stockpiles**: D_STOCKPILES → define storage area

**DON'T waste turns just looking around.** The observation already includes status, food, drink, population, and the current screen. Do NOT press z/status/announcements/reports in the opening turns.

If you're unsure what to do, **ALWAYS dig**. Designate a small 3x3 mining area - it's always useful.
If a construction screen says `Needs building material`, the live UI overrides the
stock counter. Acquire new usable material first; do not retry the same build
placement just because Wood or Stone is greater than 0.

**MAINTAIN YOUR OWN MAP MEMORY:** You have memory tools. Use them to remember
locations of workshops, dwarf clusters, resources, stairs, rooms, and blocked
placement attempts. Before retrying a placement or navigation plan, query memory
and avoid repeating attempts that previously produced no tracked DF state change.
Memory is a notebook, not an action; you still need to submit a KEYSTROKE action
each turn.

**FRESH TARGET RULE:** If status includes `Fresh target recommended keys` or
`Retry fresh target recommended keys`, copy those keys exactly. This harness starts the
camera and cursor on a reachable native-UI target near your dwarves. If the setup mode
is `material`, those keys either chop a visible tree for logs or mine visible
stone/vein wall so the fortress has real workshop building material. If status says
`Live UI material recovery`, copy the full recommended sequence exactly: the leading
LEAVESCREEN keys are there to exit build/material menus before the chop/mine target.
Retry keys are shown after failed attempts for a bounded retry.

If status says the recommended keys are hidden, stop using that target's old sequence.
Do not repeat the same key sequence for that target.
If `Live UI feedback` says `last_action_work_delta=0` or the no-progress streak is rising,
use shown retry/fresh keys if present; otherwise choose a different useful action or wait
only if dwarves still have active work.

Default recommended first action:
{
  "type": "KEYSTROKE",
  "params": {"keys": ["D_DESIGNATE", "DESIGNATE_STAIR_DOWN", "CURSOR_LEFT", "CURSOR_LEFT", "CURSOR_LEFT", "CURSOR_LEFT", "CURSOR_UP", "CURSOR_UP", "SELECT", "CURSOR_RIGHT", "CURSOR_RIGHT", "CURSOR_RIGHT", "CURSOR_DOWN", "SELECT", "LEAVESCREEN"]},
  "intent": "designate a reachable starter stair dig through the DF UI",
  "advance_ticks": 500
}

Use LEAVESCREEN only to exit SUB-menus (like after designating an area).

Tips:
- If Food/Drink is 0, the fortress is starving - dig for underground water/farms
- Mining creates space and resources - when in doubt, DIG MORE
- Don't check the same menu repeatedly - check once, then ACT

## Screen
You see the current game screen as text (80 columns x 25 rows). The screen shows the DF interface including menus, the map view, and status information.

## Actions
Return a KEYSTROKE action with a list of key names to press in sequence.
Include objective, expected_visible_result, expected_simulation_result, and
memory_update fields so the trace can compare what you expected against what
actually happened.

## Tools
You can call the df_wiki tool to look up gameplay rules and commands. Use it when you
are unsure about designations, buildings, orders, stockpiles, or other mechanics.

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
- D_BUILDING - Open building construction menu (b key)
- D_BUILDJOB - Inspect/manage a nearby existing building; this is NOT the construction menu
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

### Building Construction (after D_BUILDING)
- HOTKEY_BUILDING_WORKSHOP - Workshop category
- HOTKEY_BUILDING_WORKSHOP_CARPENTER - Carpenter's workshop
- Example carpenter workshop path: D_BUILDING, HOTKEY_BUILDING_WORKSHOP, HOTKEY_BUILDING_WORKSHOP_CARPENTER, SELECT

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
  "intent": "Brief description of what you're trying to do",
  "objective": "Current gameplay task",
  "expected_visible_result": "Immediate screen/menu/cursor/map result",
  "expected_simulation_result": "World result after ticks, or none for UI-only actions",
  "memory_update": "POI/failure review or update made before acting",
  "advance_ticks": 200
}

## Time Control (IMPORTANT!)
YOU control time. The game is PAUSED until you request time to pass.

- **advance_ticks: 0** - No time passes. Use for menu navigation, looking around.
- **advance_ticks: 100-200** - Let dwarves work briefly. Good after giving orders.
- **advance_ticks: 500+** - Watch significant progress. Use after designating dig areas.

**Strategy:**
1. Navigate menus with advance_ticks: 0 (instant, no time wasted)
2. After completing an action (dig designation, build order), set advance_ticks: 200+ to let dwarves work
3. If you see danger or need to react quickly, use advance_ticks: 0 to stay in control

Your previous actions show how much time you requested in parentheses, e.g., "(+200t)" or "(paused)".

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


KEYSTROKE_POI_REVIEW_APPENDIX = """

## Mandatory POI/Task Review Variant
You are running in an experiment that measures whether memory review improves
real Dwarf Fortress gameplay through native keystrokes. The game is usually
paused during planning/UI work, which is fine: menus, cursor movement,
designation, building placement, and inspection all work while paused. Dwarves
only dig, chop, haul, build, or produce after you choose advance_ticks > 0.

Before EVERY submit_action:
1. Call query_memory for the current objective, current menu/building target,
   or nearby coordinates. Treat this as your pre-action notebook review.
2. Read RECENT ACTION OUTCOMES. If the same placement/menu/cursor plan recently
   produced no tracked state change, do not repeat it.
3. If the observation says repeated no-progress, target refreshed after
   no-progress, or no_progress_streak >= 2, call remember_failed_attempt before
   submitting the next action.
4. If you discover or create a stable POI such as a workshop, staircase,
   stockpile, resource patch, dwarf cluster, or blocked placement area, call
   remember_poi before submitting the next action.
5. In submit_action include objective, expected_visible_result,
   expected_simulation_result, and memory_update.

Do not spend more than two consecutive actions trying to place the same workshop
or selecting the same workshop key. If placement is unclear, return to the main
view, query memory, record the failed attempt, and choose a different productive
branch such as designating fresh dig/chop work or making a stockpile.

If workshop placement has already failed twice, do not move the placement cursor
around looking for a tile. Switch strategy: exit the build menu, use any fresh
target recommended keys exactly, create a stockpile, or designate new dig/chop
work. If the cursor is off-map (for example x=-30000), do not try k/u/status
menus to recenter; exit submenus and choose a productive main-menu action.
"""


KEYSTROKE_POI_REVIEW_SYSTEM_PROMPT = (
    KEYSTROKE_SYSTEM_PROMPT + KEYSTROKE_POI_REVIEW_APPENDIX
)


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
            "objective": {
                "type": "string",
                "description": "Current gameplay task this action advances",
            },
            "expected_visible_result": {
                "type": "string",
                "description": "Immediate screen/menu/cursor/map result expected after the keys are sent",
            },
            "expected_simulation_result": {
                "type": "string",
                "description": "Dwarf/world result expected after advancing ticks, or none for UI-only actions",
            },
            "memory_update": {
                "type": "string",
                "description": "POI/failure memory reviewed or updated before acting",
            },
            "advance_ticks": {
                "type": "integer",
                "minimum": 0,
                "maximum": 2000,
                "default": 0,
                "description": "Number of game ticks to advance after keystrokes. 0 = stay paused (for menu navigation). 100-500 = let dwarves work.",
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


def _usage_payload(response: Any) -> Dict[str, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    keys = (
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    )
    payload: Dict[str, int] = {}
    for key in keys:
        value = getattr(usage, key, None)
        if value is not None:
            payload[key] = int(value)
    return payload


def _append_usage_event(
    events: List[Dict[str, Any]],
    response: Any,
    *,
    model: str,
    max_tokens: int,
    temperature: float,
) -> None:
    usage = _usage_payload(response)
    if not usage:
        return
    events.append(
        {
            "tool": "anthropic.messages.create",
            "input": {
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            "output": {"usage": usage},
        }
    )


class AnthropicActionAgent(Agent):
    """Calls Anthropic Messages API with tool-use for submit_action."""

    def __init__(self, *, system_prompt: str = system_prompt_v1) -> None:
        self._settings = get_settings()
        if not self._settings.ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY not configured")
        self._system_prompt = system_prompt
        self._client = None
        self._last_call = 0.0
        self._tool_events: List[Dict[str, Any]] = []

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
                system=self._system_prompt,
                tools=[ANTHROPIC_TOOL],
                messages=[
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": content}],
                    }
                ],
            )
            _append_usage_event(
                self._tool_events,
                response,
                model=self._settings.ANTHROPIC_MODEL,
                max_tokens=self._settings.LLM_MAX_TOKENS,
                temperature=self._settings.LLM_TEMP,
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

    def pop_tool_events(self) -> List[Dict[str, Any]]:
        events = list(self._tool_events)
        self._tool_events.clear()
        return events


register_agent("anthropic", lambda: AnthropicActionAgent())


class AnthropicDigFirstAgent(AnthropicActionAgent):
    """Structured Anthropic policy that starts with a direct DFHack DIG action."""

    def __init__(self) -> None:
        super().__init__(system_prompt=DIG_FIRST_SYSTEM_PROMPT)


register_agent("anthropic-dig-first", lambda: AnthropicDigFirstAgent())


class AnthropicFortressPlanAgent(AnthropicActionAgent):
    """Structured Anthropic policy for a visible two-room fortress plan."""

    def __init__(self) -> None:
        super().__init__(system_prompt=FORTRESS_PLAN_SYSTEM_PROMPT)


register_agent("anthropic-fortress-plan", lambda: AnthropicFortressPlanAgent())


class AnthropicKeystrokeAgent(Agent):
    """Anthropic agent for keystroke-based game control."""

    def __init__(
        self,
        *,
        system_prompt: str = KEYSTROKE_SYSTEM_PROMPT,
        require_memory_review: bool = False,
    ) -> None:
        self._settings = get_settings()
        if not self._settings.ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY not configured")
        self._client = None
        self._last_call = 0.0
        self._system_prompt = system_prompt
        self._require_memory_review = require_memory_review
        self._memory = MemoryManager(window_size=self._resolve_memory_window())
        self._pending_observation: Optional[str] = None
        self._pending_action: Optional[Dict[str, Any]] = None
        self._tool_manager = ToolManager(
            ["df_wiki", "remember_poi", "remember_failed_attempt", "query_memory"],
            memory=self._memory,
        )
        self._tool_events: List[Dict[str, Any]] = []

    def _resolve_memory_window(self) -> int:
        env_value = os.getenv("FORT_GYM_MEMORY_WINDOW")
        if env_value is not None:
            return int(env_value)
        return self._settings.MEMORY_WINDOW

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

    def _required_memory_review_error(
        self,
        tool_uses: List[Any],
        obs_text: str,
        tool_payload: Dict[str, Any] | None,
    ) -> Optional[str]:
        if not self._require_memory_review:
            return None
        tool_names = {str(getattr(tool_use, "name", "")) for tool_use in tool_uses}
        if "query_memory" not in tool_names:
            return (
                "Mandatory pre-action review missing: call query_memory for the "
                "current objective/menu/POI before submit_action."
            )
        if self._needs_failed_attempt_memory(obs_text) and "remember_failed_attempt" not in tool_names:
            return (
                "Mandatory failed-attempt update missing: the observation shows "
                "repeated or recent no-progress behavior. Call remember_failed_attempt "
                "before submit_action and choose a different plan."
            )
        if self._needs_workshop_strategy_switch(obs_text, tool_payload):
            return (
                "Workshop placement loop detected: do not attempt another workshop "
                "placement or placement-cursor navigation. Record/consult memory and "
                "submit a different productive branch such as exact fresh target keys, "
                "dig/chop designation, or stockpile creation."
            )
        return None

    @staticmethod
    def _needs_failed_attempt_memory(obs_text: str) -> bool:
        if "target refreshed after repeated no-progress" in obs_text:
            return True
        if "the last action changed no tracked tiles" in obs_text:
            return True
        if "do not repeat the same key sequence" in obs_text:
            return True
        match = re.search(r"no_progress_streak=(\d+)", obs_text)
        return bool(match and int(match.group(1)) >= 2)

    @staticmethod
    def _needs_workshop_strategy_switch(
        obs_text: str,
        tool_payload: Dict[str, Any] | None,
    ) -> bool:
        if not isinstance(tool_payload, dict):
            return False
        params = tool_payload.get("params") if isinstance(tool_payload.get("params"), dict) else {}
        keys = params.get("keys") if isinstance(params, dict) else []
        action_focus = {
            "keys": keys if isinstance(keys, list) else [],
            "intent": tool_payload.get("intent"),
            "objective": tool_payload.get("objective"),
            "expected_visible_result": tool_payload.get("expected_visible_result"),
        }
        payload_text = json.dumps(action_focus, ensure_ascii=True).lower()
        key_text = json.dumps(action_focus["keys"], ensure_ascii=True).lower()
        workshop_key_requested = "hotkey_building_workshop" in key_text
        text_requests_workshop = any(
            marker in payload_text
            for marker in (
                "workshop",
                "carpenter",
                "mason",
                "craftsdwarf",
                "leather works",
                "hotkey_building_workshop",
            )
        ) and any(verb in payload_text for verb in ("place", "placement", "build", "select"))
        recovery_text = "switch away" in payload_text or "avoid" in payload_text
        workshop_requested = workshop_key_requested or (text_requests_workshop and not recovery_text)
        if not workshop_requested:
            return False
        text = obs_text.lower()
        failed_workshop_mentions = text.count("failed") + text.count("no tracked state")
        has_workshop_failure_memory = (
            "recent failed attempts:" in text
            and any(marker in text for marker in ("workshop", "placement", "blocked"))
        )
        repeated_workshop_outcomes = (
            text.count("workshop") >= 3
            and (
                text.count("changed=none") >= 2
                or text.count("keys_sent_without_tracked_state_change") >= 2
            )
        )
        off_map_cursor = "cursor=(-30000" in text or '"cursor_x": -30000' in text
        return (
            has_workshop_failure_memory
            or repeated_workshop_outcomes
            or (off_map_cursor and failed_workshop_mentions >= 2)
        )

    def decide(self, obs_text: str, obs_json: Dict[str, Any]) -> Dict[str, Any]:
        """Decide on a keystroke action based on screen observation."""
        # For keystroke mode, obs_text already contains screen + status
        # We don't need to include full JSON state since screen is the primary input
        if self._pending_observation is not None and self._pending_action is not None:
            self._memory.add_step(self._pending_observation, self._pending_action, obs_text)

        memory_context = self._memory.get_context()
        if memory_context:
            content = f"{memory_context}\n\n== CURRENT OBSERVATION ==\n{obs_text}"
        else:
            content = obs_text

        last_error: Optional[Exception] = None
        messages: List[Dict[str, Any]] = [
            {"role": "user", "content": [{"type": "text", "text": content}]}
        ]
        tools = [KEYSTROKE_ANTHROPIC_TOOL, *self._tool_manager.tool_specs()]
        tool_result_cache: Dict[str, str] = {}

        def append_tool_retry(response_content: Any, tool_results: List[Dict[str, Any]]) -> None:
            messages.append({"role": "assistant", "content": response_content})
            messages.append({"role": "user", "content": tool_results})

        def tool_result(tool_use: Any, content: str) -> Dict[str, Any]:
            return {
                "type": "tool_result",
                "tool_use_id": tool_use.id,
                "content": content,
            }

        def tool_results_for_retry(tool_uses: List[Any], submit_error: str) -> List[Dict[str, Any]]:
            results = []
            for tool_use in tool_uses:
                if tool_use.name == "submit_action":
                    results.append(tool_result(tool_use, submit_error))
                    continue
                tool_input = tool_use.input or {}
                if not isinstance(tool_input, dict):
                    tool_input = {"input": tool_input}
                cache_key = getattr(tool_use, "id", "")
                if cache_key and cache_key in tool_result_cache:
                    result = tool_result_cache[cache_key]
                else:
                    result = self._tool_manager.handle(tool_use.name, tool_input)
                    if cache_key:
                        tool_result_cache[cache_key] = result
                    self._tool_events.append(
                        {
                            "tool": tool_use.name,
                            "input": tool_input,
                            "output": result,
                        }
                    )
                results.append(tool_result(tool_use, result))
            if not results:
                results.append(
                    {
                        "type": "text",
                        "text": submit_error,
                    }
                )
            return results

        for attempt_index in range(5):
            tool_result_cache.clear()
            self._rate_limit()
            client = self._client_instance()
            response = client.messages.create(
                model=self._settings.ANTHROPIC_MODEL,
                max_tokens=self._settings.LLM_MAX_TOKENS,
                temperature=self._settings.LLM_TEMP,
                system=self._system_prompt,
                tools=tools,
                messages=messages,
            )
            _append_usage_event(
                self._tool_events,
                response,
                model=self._settings.ANTHROPIC_MODEL,
                max_tokens=self._settings.LLM_MAX_TOKENS,
                temperature=self._settings.LLM_TEMP,
            )

            tool_payload = None
            tool_uses = []
            for item in response.content:
                if item.type == "tool_use":
                    tool_uses.append(item)
                    if item.name == "submit_action":
                        tool_payload = item.input

            for tool_use in tool_uses:
                if tool_use.name == "submit_action":
                    continue
                tool_input = tool_use.input or {}
                if not isinstance(tool_input, dict):
                    tool_input = {"input": tool_input}
                result = self._tool_manager.handle(tool_use.name, tool_input)
                cache_key = getattr(tool_use, "id", "")
                if cache_key:
                    tool_result_cache[cache_key] = result
                self._tool_events.append(
                    {
                        "tool": tool_use.name,
                        "input": tool_input,
                        "output": result,
                    }
                )

            if tool_payload is not None:
                required_review_error = self._required_memory_review_error(
                    tool_uses,
                    obs_text,
                    tool_payload,
                )
                if required_review_error and attempt_index < 2:
                    last_error = ValueError(required_review_error)
                    append_tool_retry(
                        response.content,
                        tool_results_for_retry(tool_uses, required_review_error),
                    )
                    continue
                if required_review_error:
                    self._tool_events.append(
                        {
                            "tool": "memory_review_gate_warning",
                            "input": {
                                "attempt": attempt_index + 1,
                                "required_review_error": required_review_error,
                            },
                            "output": "Allowed action after bounded memory-review retries.",
                        }
                    )

                # Validate it's a KEYSTROKE action
                if tool_payload.get("type") != "KEYSTROKE":
                    last_error = ValueError(
                        f"Expected KEYSTROKE action, got {tool_payload.get('type')}"
                    )
                    append_tool_retry(
                        response.content,
                        tool_results_for_retry(tool_uses, "You must return a KEYSTROKE action."),
                    )
                    continue

                params = tool_payload.get("params", {})
                keys = params.get("keys", [])
                if not keys or not isinstance(keys, list):
                    last_error = ValueError("KEYSTROKE action must have non-empty keys list")
                    append_tool_retry(
                        response.content,
                        tool_results_for_retry(
                            tool_uses,
                            "KEYSTROKE action requires a non-empty keys list.",
                        ),
                    )
                    continue

                try:
                    action = parse_action(tool_payload)
                except ValueError as exc:
                    last_error = exc
                    append_tool_retry(
                        response.content,
                        tool_results_for_retry(
                            tool_uses,
                            f"Previous response invalid ({exc}). Provide valid KEYSTROKE action.",
                        ),
                    )
                    continue

                self._pending_observation = obs_text
                self._pending_action = action
                return action

            if tool_uses:
                append_tool_retry(
                    response.content,
                    tool_results_for_retry(
                        tool_uses,
                        "Use submit_action with a KEYSTROKE action.",
                    ),
                )
                continue

            last_error = ValueError("Model did not return an action")
            messages.append({"role": "assistant", "content": response.content})
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Please use the submit_action tool to send keystrokes."}
                    ],
                }
            )

        raise RuntimeError(f"Anthropic keystroke agent failed: {last_error}")

    def pop_tool_events(self) -> List[Dict[str, Any]]:
        events = list(self._tool_events)
        self._tool_events.clear()
        return events


register_agent("anthropic-keystroke", lambda: AnthropicKeystrokeAgent())
register_agent(
    "anthropic-keystroke-poi-review",
    lambda: AnthropicKeystrokeAgent(
        system_prompt=KEYSTROKE_POI_REVIEW_SYSTEM_PROMPT,
        require_memory_review=True,
    ),
)


__all__ = [
    "AnthropicActionAgent",
    "AnthropicDigFirstAgent",
    "AnthropicFortressPlanAgent",
    "AnthropicKeystrokeAgent",
    "DIG_FIRST_SYSTEM_PROMPT",
    "FORTRESS_PLAN_SYSTEM_PROMPT",
    "KEYSTROKE_SYSTEM_PROMPT",
    "KEYSTROKE_POI_REVIEW_SYSTEM_PROMPT",
]
