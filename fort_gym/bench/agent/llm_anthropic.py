"""Anthropic tool-use agent adapter."""

from __future__ import annotations

import json
import os
import re
import time
from copy import deepcopy
from importlib import import_module
from types import SimpleNamespace
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
3. **Create stockpiles**: D_STOCKPILES → STOCKPILE_WOOD/STONE/etc. → define storage area

**DON'T waste turns just looking around.** The observation already includes status, food, drink, population, and the current screen. Do NOT press z/status/announcements/reports in the opening turns.

If you're unsure what to do, **ALWAYS dig**. Designate a small 3x3 mining area - it's always useful.
If a construction screen says `Needs building material`, the live UI overrides the
stock counter. Acquire new usable material first; do not retry the same build
placement just because Wood or Stone is greater than 0.
The starting stock counter can include material that DF will not accept for a
new workshop. Treat `Live UI run progress: total_material_delta > 0` as the
stronger signal that this run has created usable building material.

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
If the setup mode is `workshop`, the target is a candidate 3x3 floor footprint.
Copy the recommended carpenter-workshop keys to open native placement mode, then
read the visible placement screen before confirming. Do not press SELECT to place
the workshop unless your screen_read verifies the placement UI does not say
`Blocked` or `Needs building material`. The visible DF screen overrides
`selection_rect`, `placement_rect`, and target metadata.
Retry keys are shown after failed attempts for a bounded retry.

If status says the recommended keys are hidden, stop using that target's old sequence.
Do not repeat the same key sequence for that target.
Do not derive a long key path by subtracting `selection_rect` from `window`;
those fields are observation metadata, not a manual cursor-navigation recipe.
Only navigate manually by cursor if the current screen visibly shows an active
X cursor in a cursor-owning DF mode and your screen_read can verify it.
If `Live UI feedback` says `last_action_work_delta=0` or the no-progress streak is rising,
use shown retry/fresh keys if present; otherwise choose a different useful action or wait
only if dwarves still have active work.
If `Live view` says `cursor_inactive=(-30000,...)`, that is DF's sentinel for
"no active cursor on this screen," not proof that all future cursor movement is
broken. Open a cursor-owning mode such as D_DESIGNATE, D_STOCKPILES, or
D_BUILDING, then judge the visible cursor/menu from the next screen.
If `carpenter_workshops=1` and `manager_orders=0`, your next major objective is
production, not another workshop. Prefer D_JOBLIST -> UNITJOB_MANAGER ->
MANAGER_NEW_ORDER or a visibly selected carpenter workshop job menu before
retrying stockpiles or blind dig boxes. If a stockpile or dig path has already
produced no tracked state change after the workshop exists, record it and return
to production.
If a carpenter workshop screen is selected, use BUILDJOB_ADD to open its native
task list. Opening the add-task UI is not production by itself: read the next
screen, select a concrete task such as a wooden bed/barrel/bin, then advance
time only after a real task is queued or visible workshop work has changed.
In the workshop add-task list, SELECT chooses the currently highlighted row.
Do not assume parenthesized letters such as `(b)` work through raw STRING_A###
hotkeys; if the desired task is visible but not highlighted, move the selection
with scroll/navigation keys first, then SELECT. If you accidentally queue a
different job such as `Make wooden shield`, report that exact job and either let
it run as useful production or reopen the add-task list to choose the intended
job; do not call it a bed.
For visible add-task lists, prefer CURSOR_DOWN/CURSOR_UP for row selection.
Count visible rows from the current top/highlighted row to the desired task and
then press SELECT. Example: if `Construct Bed (b)` is visible 11 rows below the
top item, send eleven CURSOR_DOWN keys followed by SELECT; do not test the raw
`STRING_A098` letter first.
If `SCREEN VISUAL HINTS` appears, use it as raw CopyScreen highlight evidence.
For example, a hinted row in an add-task list is the row DF currently appears to
highlight; scroll or navigate until the desired visible task is highlighted
before pressing SELECT. The visual hints are not recommended actions and do not
replace your own screen_read verification.

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
When present, `SCREEN VISUAL HINTS` preserves raw CopyScreen foreground/background
highlight information that the plain text grid cannot show. Use it to identify
the currently highlighted menu row or cursor-like screen element.

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

### Typing Letters
Many DF menus show options like "a - Do something". If no named interface key
exists below, type the letter using STRING_A### format where ### is the ASCII code:
- STRING_A097 = 'a', STRING_A098 = 'b', STRING_A099 = 'c', STRING_A100 = 'd'
- STRING_A101 = 'e', STRING_A102 = 'f', STRING_A103 = 'g', STRING_A104 = 'h'
- STRING_A105 = 'i', STRING_A106 = 'j', STRING_A107 = 'k', STRING_A108 = 'l'
- STRING_A109 = 'm', STRING_A110 = 'n', STRING_A111 = 'o', STRING_A112 = 'p'
- STRING_A113 = 'q', STRING_A114 = 'r', STRING_A115 = 's', STRING_A116 = 't'
- STRING_A117 = 'u', STRING_A118 = 'v', STRING_A119 = 'w', STRING_A120 = 'x'
- STRING_A121 = 'y', STRING_A122 = 'z'

Example: If you see "a - Finish conversation", send STRING_A097 to press 'a'.
Do not use STRING_A### when the key reference lists a named menu key; named
interface keys are more reliable. Example: in the stockpile menu use
STOCKPILE_WOOD, not STRING_A119.

### Main Menus (press from main view)
- D_DESIGNATE - Open designate menu (d key)
- D_BUILDING - Open building construction menu (b key)
- D_BUILDJOB - Inspect/manage a nearby existing building; this is NOT the construction menu
- D_STOCKPILES - Open stockpiles menu (p key)
- D_ZONES - Open zones menu (i key)
- D_ORDERS - Open standing orders (o key); this is NOT the manager work-order queue
- D_JOBLIST - Open jobs/work-order screens (j key). Use this before manager work-order keys.

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

### Stockpile Menu (after D_STOCKPILES)
- STOCKPILE_WOOD - Choose Wood stockpile type
- STOCKPILE_STONE - Choose Stone stockpile type
- STOCKPILE_FOOD - Choose Food stockpile type
- STOCKPILE_BAR - Choose Bar/Block stockpile type
- After selecting a stockpile type, use CURSOR keys and SELECT twice to define
  the rectangle, then LEAVESCREEN to exit.

### Manager / Work Orders
- D_ORDERS opens standing orders only. If you are trying to queue production
  such as beds, doors, tables, chairs, barrels, or bins, do not use D_ORDERS.
- Use D_JOBLIST to reach the jobs/work-order area. If the footer shows
  `m: Manager`, use UNITJOB_MANAGER, not STRING_A109. Once the manager screen
  is visible, use MANAGER_NEW_ORDER to add a production order.
- D_BUILDJOB acts on the building under the current cursor. If it opens a
  stockpile or some other building, it did not target your remembered workshop;
  exit, query memory, and re-establish a visible cursor on the workshop before
  trying building-job commands again.
- On a selected carpenter workshop screen, use BUILDJOB_ADD, not raw STRING_A097,
  to add a native workshop task. Then read the task-selection screen and select a
  concrete useful job. Do not count the add-task menu opening as success unless
  a job row/task appears or later ticks show workshop work/material progress.
- In the workshop add-task list, SELECT picks the highlighted row. Parenthesized
  letters like `Construct Bed (b)` are visible labels, but raw STRING_A### may
  not select them in this menu. If a desired row is visible lower in the list,
  count the visible rows and use repeated CURSOR_DOWN/CURSOR_UP before SELECT.
  Example: from the top row, use eleven CURSOR_DOWN keys then SELECT for a
  visible `Construct Bed (b)` eleven rows down. Prefer CURSOR_DOWN over
  STANDARDSCROLL/SECONDSCROLL for row selection, and verify the actual queued
  job on the next screen.

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
- Viewport scroll keys like STANDARDSCROLL_PAGEDOWN do not advance simulation
  time. If your intent says wait, advance time, or let dwarves work, set
  advance_ticks to a positive value.
- To press the visible Space pause/resume command, use `STRING_A032`; do not
  use `PAUSE` for live gameplay recovery.
- If your keys complete a work designation such as dig/chop/stairs with two
  SELECT corners and LEAVESCREEN, set advance_ticks to 500+ so dwarves can act
  on the new job before your next decision.

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
work. If `Live view` reports `cursor_inactive=(-30000,...)`, distinguish that
inactive sentinel from a visible off-map cursor. In main_map it usually means no
cursor-owning mode is open yet; in a cursor placement menu without a visible X,
exit once and choose a productive named menu action or fresh target.
If fresh target keys are hidden, treat `selection_rect` and `window` as notes
about the observed target, not a route. Do not record or submit coordinate-offset
plans unless your current screen_read identifies a visible active cursor in the
right DF mode.
"""


KEYSTROKE_POI_REVIEW_SYSTEM_PROMPT = (
    KEYSTROKE_SYSTEM_PROMPT + KEYSTROKE_POI_REVIEW_APPENDIX
)


KEYSTROKE_PLAN_REVIEW_APPENDIX = """

## Periodic Gameplay Plan Review Variant
You are running in a hill-climbing experiment. Your job is not only to press
keys; it is to maintain and periodically critique your own plan against the
real visible game state.

Use the plan tools as a private notebook:
- Before your first submit_action, call write_gameplay_plan with a concrete
  multi-step plan. The plan should include: reachable excavation, material
  acquisition if needed, workshop placement, and then a post-workshop branch
  that creates production work before stockpile refinement or more room digging.
  If `manager_orders=0`, prefer production orders or a visible
  carpenter-workshop job menu before stockpile refinement or room completion.
- At least every five submitted actions, call review_gameplay_plan before
  submit_action. Also call it immediately when recent outcomes show
  no_progress_streak >= 2, repeated no state change, or a completed milestone.
- A review must compare the stored plan to evidence from the screen/status and
  recent action outcomes. If the current step is done or blocked, revise the
  next step instead of repeating the same key sequence.
- If a carpenter workshop already exists, stop trying to place more workshops
  unless the screen/state proves the next workshop is necessary. Shift to
  direct workshop tasks or useful orders through native UI before stockpile or
  room refinement.
- Include plan_step and plan_review in submit_action so the trace can audit
  whether the action follows the reviewed plan.

The plan is not scoring and does not change Dwarf Fortress. The only way to
score is still real gameplay through keystrokes, visible map/material changes,
and ticks that let dwarves act.
"""


KEYSTROKE_PLAN_REVIEW_SYSTEM_PROMPT = (
    KEYSTROKE_POI_REVIEW_SYSTEM_PROMPT + KEYSTROKE_PLAN_REVIEW_APPENDIX
)


KEYSTROKE_PERCEPTION_REVIEW_APPENDIX = """

## Agent-Owned Perception and Verification Contract
You are running in the strict no-cheat perception experiment. The harness only
supplies raw DF observations and enforces that you write down your own
interpretation before acting. It does not classify menus, pick keys, or decide
strategy for you.

Before EVERY submit_action:
1. Call record_screen_read with your own reading of the current screen.
   - mode: one of main_map, designation_menu, building_menu,
     workshop_placement, stockpile_menu, orders_menu, job_list,
     announcement_screen, material_selection, unknown.
   - evidence: one to three short facts from visible screen text/tiles/status.
   - cursor_or_selection: what you believe the cursor or active selection is.
     Distinguish a visible X cursor from `cursor_inactive=(-30000,...)`, which
     only means the current screen has no active DF cursor exposed.
   - confidence: high, medium, or low. If unsure, use unknown and low.
2. Call review_last_action with your own verification of the previous submitted action.
   - worked: true, false, or null for the first action.
   - evidence: one to three facts comparing the previous expected result to the
     current screen/status/recent outcome row.
   - mismatch_reason: why it did not work, or empty/null when it worked.
   - should_retry_same_path: true only if you have new evidence that retrying
     the same path is appropriate.
3. Then call submit_action. You may also include screen_read and
   last_action_review in submit_action, but the mandatory tools above are the
   source of truth for this experiment.

If last_action_review says the previous path did not work, do not press the same
menu/key path again unless your evidence names a changed condition. Prefer a
different productive branch, a clean exit to main view, or time advancement only
when dwarves have active work to complete.
If the previous action only opened or stayed on a carpenter workshop task menu,
mark it worked=false for production unless the current screen shows a concrete task row/job choice or the recent outcome row shows real workshop/material work.
If the previous action tried a parenthesized workshop task letter and the same add-task list is still visible, mark it worked=false and switch to scroll/select navigation or a different production path instead of retrying the raw letter.
If your proposed action uses manual cursor movement, your screen_read evidence
must identify the visible active cursor or active selection on the current
screen. `selection_rect` and `window` alone do not satisfy that evidence.

These fields are your cognition trail. They do not change Dwarf Fortress and
they are not scoring. Real score still only comes from native keystrokes,
visible map/material/building changes, and ticks that let dwarves act.
"""


KEYSTROKE_PERCEPTION_REVIEW_SYSTEM_PROMPT = (
    KEYSTROKE_PLAN_REVIEW_SYSTEM_PROMPT + KEYSTROKE_PERCEPTION_REVIEW_APPENDIX
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
            "screen_read": {
                "type": "object",
                "description": "Your own reading of the current DF screen before acting.",
                "properties": {
                    "mode": {
                        "type": "string",
                        "description": "Current screen/menu mode as you infer it from visible evidence.",
                    },
                    "evidence": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Visible screen/status facts supporting your mode read.",
                    },
                    "cursor_or_selection": {
                        "type": "string",
                        "description": "What cursor, highlighted item, or active selection appears to be current.",
                    },
                    "confidence": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                    },
                },
                "required": ["mode", "evidence", "confidence"],
            },
            "last_action_review": {
                "type": "object",
                "description": "Your own verification of the previous action against the current observation.",
                "properties": {
                    "worked": {
                        "type": ["boolean", "null"],
                        "description": "Whether the previous action appears to have worked; null for the first action.",
                    },
                    "evidence": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Facts comparing the previous expectation to the current screen/status/outcome.",
                    },
                    "mismatch_reason": {
                        "type": ["string", "null"],
                        "description": "Why the previous action failed or diverged, if it did.",
                    },
                    "should_retry_same_path": {
                        "type": "boolean",
                        "description": "Whether retrying the same menu/key path is justified by new evidence.",
                    },
                },
                "required": ["worked", "evidence", "should_retry_same_path"],
            },
            "memory_update": {
                "type": "string",
                "description": "POI/failure memory reviewed or updated before acting",
            },
            "plan_step": {
                "type": "string",
                "description": "Current agent-maintained plan step this action advances",
            },
            "plan_review": {
                "type": "string",
                "description": "Brief summary of the latest plan review used before acting",
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


def _keystroke_anthropic_tool(*, require_perception_review: bool = False) -> Dict[str, Any]:
    tool_spec = deepcopy(KEYSTROKE_TOOL_SPEC)
    if require_perception_review:
        required = list(tool_spec["parameters"].get("required", []))
        for field in ("screen_read", "last_action_review", "advance_ticks"):
            if field not in required:
                required.append(field)
        tool_spec["parameters"]["required"] = required
    return {
        "name": tool_spec["name"],
        "description": tool_spec["description"],
        "input_schema": tool_spec["parameters"],
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
    temperature: float | None,
) -> None:
    usage = _usage_payload(response)
    if not usage:
        return
    request_input: Dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
    }
    if temperature is not None:
        request_input["temperature"] = temperature
    events.append(
        {
            "tool": "anthropic.messages.create",
            "input": request_input,
            "output": {"usage": usage},
        }
    )


def _model_rejects_sampling_params(model: str) -> bool:
    return model.startswith(("claude-opus-4-7", "claude-opus-4-8"))


def _request_temperature(model: str, configured_temperature: float) -> float | None:
    if _model_rejects_sampling_params(model):
        return None
    return configured_temperature


def _is_rate_limit_error(exc: Exception) -> bool:
    if exc.__class__.__name__ == "RateLimitError":
        return True
    status_code = getattr(exc, "status_code", None)
    return status_code == 429


def _is_retryable_anthropic_error(exc: Exception) -> bool:
    if _is_rate_limit_error(exc):
        return True
    class_name = exc.__class__.__name__
    if "Timeout" in class_name or class_name == "APIConnectionError":
        return True
    status_code = getattr(exc, "status_code", None)
    return status_code in {408, 409, 425, 500, 502, 503, 504, 529}


def _retry_backoff_seconds(attempt: int, *, rate_limited: bool) -> float:
    base_seconds = 15.0 if rate_limited else 5.0
    max_seconds = 120.0 if rate_limited else 60.0
    return min(max_seconds, base_seconds * (2**attempt))


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
            self._client = client_cls(
                api_key=self._settings.ANTHROPIC_API_KEY,
                timeout=self._settings.ANTHROPIC_TIMEOUT_SECONDS,
            )
        return self._client

    def _create_message_with_retries(self, client: Any, **kwargs: Any) -> Any:
        last_error: Exception | None = None
        max_attempts = max(1, self._settings.ANTHROPIC_MAX_ATTEMPTS)
        for attempt in range(max_attempts):
            try:
                return client.messages.create(**kwargs)
            except Exception as exc:
                if not _is_retryable_anthropic_error(exc) or attempt + 1 >= max_attempts:
                    raise
                last_error = exc
                rate_limited = _is_rate_limit_error(exc)
                wait_seconds = _retry_backoff_seconds(
                    attempt,
                    rate_limited=rate_limited,
                )
                tool_name = (
                    "anthropic.rate_limit_retry"
                    if rate_limited
                    else "anthropic.request_retry"
                )
                self._tool_events.append(
                    {
                        "tool": tool_name,
                        "input": {"attempt": attempt + 1, "wait_seconds": wait_seconds},
                        "output": str(exc),
                    }
                )
                time.sleep(wait_seconds)
        if last_error is not None:
            raise last_error
        raise RuntimeError("Anthropic request failed without an exception")

    def decide(self, obs_text: str, obs_json: Dict[str, Any]) -> Dict[str, Any]:
        content = f"{obs_text}\n\nState JSON:\n{json.dumps(obs_json)}"
        last_error: Optional[Exception] = None

        for _ in range(3):
            self._rate_limit()
            client = self._client_instance()
            model = self._settings.ANTHROPIC_MODEL
            temperature = _request_temperature(model, self._settings.LLM_TEMP)
            request_kwargs: Dict[str, Any] = {
                "model": model,
                "max_tokens": self._settings.LLM_MAX_TOKENS,
                "system": self._system_prompt,
                "tools": [ANTHROPIC_TOOL],
                "messages": [
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": content}],
                    }
                ],
            }
            if temperature is not None:
                request_kwargs["temperature"] = temperature
            response = self._create_message_with_retries(
                client,
                **request_kwargs,
            )
            _append_usage_event(
                self._tool_events,
                response,
                model=model,
                max_tokens=self._settings.LLM_MAX_TOKENS,
                temperature=temperature,
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
        require_plan_review: bool = False,
        require_perception_review: bool = False,
        plan_review_interval: int = 5,
        model_override: str | None = None,
    ) -> None:
        self._settings = get_settings()
        if not self._settings.ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY not configured")
        self._client = None
        self._last_call = 0.0
        self._system_prompt = system_prompt
        self._require_memory_review = require_memory_review
        self._require_plan_review = require_plan_review
        self._require_perception_review = require_perception_review
        self._plan_review_interval = max(1, int(plan_review_interval))
        self._anthropic_model = model_override or self._settings.ANTHROPIC_MODEL
        self._completed_actions = 0
        self._reviewed_plan_milestones: set[str] = set()
        self._memory = MemoryManager(window_size=self._resolve_memory_window())
        self._pending_observation: Optional[str] = None
        self._pending_action: Optional[Dict[str, Any]] = None
        self._keystroke_tool = _keystroke_anthropic_tool(
            require_perception_review=require_perception_review,
        )
        enabled_tools = ["df_wiki", "remember_poi", "remember_failed_attempt", "query_memory"]
        if require_plan_review:
            enabled_tools.extend(["write_gameplay_plan", "review_gameplay_plan"])
        if require_perception_review:
            enabled_tools.extend(["record_screen_read", "review_last_action"])
        self._tool_manager = ToolManager(enabled_tools, memory=self._memory)
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
            self._client = client_cls(
                api_key=self._settings.ANTHROPIC_API_KEY,
                timeout=self._settings.ANTHROPIC_TIMEOUT_SECONDS,
            )
        return self._client

    def _create_message_with_retries(self, client: Any, **kwargs: Any) -> Any:
        last_error: Exception | None = None
        max_attempts = max(1, self._settings.ANTHROPIC_MAX_ATTEMPTS)
        for attempt in range(max_attempts):
            try:
                return client.messages.create(**kwargs)
            except Exception as exc:
                if not _is_retryable_anthropic_error(exc) or attempt + 1 >= max_attempts:
                    raise
                last_error = exc
                rate_limited = _is_rate_limit_error(exc)
                wait_seconds = _retry_backoff_seconds(
                    attempt,
                    rate_limited=rate_limited,
                )
                tool_name = (
                    "anthropic.rate_limit_retry"
                    if rate_limited
                    else "anthropic.request_retry"
                )
                self._tool_events.append(
                    {
                        "tool": tool_name,
                        "input": {"attempt": attempt + 1, "wait_seconds": wait_seconds},
                        "output": str(exc),
                    }
                )
                time.sleep(wait_seconds)
        if last_error is not None:
            raise last_error
        raise RuntimeError("Anthropic request failed without an exception")

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
                "submit a different productive branch such as manager/job production, "
                "exact fresh target keys, dig/chop designation, or stockpile creation."
            )
        return None

    def _required_plan_review_error(
        self,
        tool_uses: List[Any],
        obs_text: str,
    ) -> Optional[str]:
        if not self._require_plan_review:
            return None
        tool_names = {str(getattr(tool_use, "name", "")) for tool_use in tool_uses}
        if self._completed_actions == 0 or not self._memory.gameplay_plan:
            if "write_gameplay_plan" not in tool_names:
                return (
                    "Mandatory gameplay plan missing: before the first action, call "
                    "write_gameplay_plan with concrete steps for excavation, material, "
                    "workshop, and post-workshop fortress-space completion."
                )
        due_by_cadence = self._completed_actions > 0 and (
            self._completed_actions % self._plan_review_interval == 0
        )
        due_by_stall = self._needs_failed_attempt_memory(obs_text)
        milestone_key = self._plan_milestone_key(obs_text)
        due_by_milestone = (
            milestone_key is not None and milestone_key not in self._reviewed_plan_milestones
        )
        if "review_gameplay_plan" in tool_names and milestone_key is not None:
            self._reviewed_plan_milestones.add(milestone_key)
        if due_by_cadence or due_by_stall or due_by_milestone:
            if "review_gameplay_plan" not in tool_names:
                reasons = []
                if due_by_cadence:
                    reasons.append(f"{self._plan_review_interval}-action checkpoint")
                if due_by_stall:
                    reasons.append("stalled/no-progress evidence")
                if due_by_milestone:
                    reasons.append("milestone/phase transition evidence")
                return (
                    "Mandatory gameplay plan review missing: call review_gameplay_plan "
                    "before submit_action because " + ", ".join(reasons) + "."
                )
        return None

    def _required_perception_review_error(
        self,
        tool_payload: Dict[str, Any] | None,
        tool_names: set[str] | None = None,
    ) -> Optional[str]:
        if not self._require_perception_review:
            return None
        tool_names = tool_names or set()
        if "record_screen_read" not in tool_names and not (
            isinstance(tool_payload, dict) and isinstance(tool_payload.get("screen_read"), dict)
        ):
            return (
                "Mandatory record_screen_read missing: call record_screen_read with "
                "your own current screen/menu read before submit_action."
            )
        if "review_last_action" not in tool_names and not (
            isinstance(tool_payload, dict)
            and isinstance(tool_payload.get("last_action_review"), dict)
        ):
            return (
                "Mandatory review_last_action missing: call review_last_action with "
                "your own previous-action verification before submit_action."
            )
        if not isinstance(tool_payload, dict):
            return "Mandatory perception review missing: submit_action payload is not an object."

        screen_read = tool_payload.get("screen_read")
        if not isinstance(screen_read, dict):
            return (
                "Mandatory screen_read missing: before submit_action, write your own "
                "current screen/menu read with mode, evidence, cursor_or_selection, "
                "and confidence."
            )
        screen_error = self._validate_screen_read(screen_read)
        if screen_error:
            return "Mandatory screen_read incomplete: " + screen_error

        last_action_review = tool_payload.get("last_action_review")
        if not isinstance(last_action_review, dict):
            return (
                "Mandatory last_action_review missing: before submit_action, compare "
                "the previous action expectation to the current observation. For the "
                "first action set worked to null and evidence to no previous action."
            )
        review_error = self._validate_last_action_review(last_action_review)
        if review_error:
            return "Mandatory last_action_review incomplete: " + review_error
        return None

    @staticmethod
    def _advance_ticks_contract_error(tool_payload: Dict[str, Any]) -> Optional[str]:
        try:
            advance_ticks = int(tool_payload.get("advance_ticks", 0))
        except (TypeError, ValueError):
            return None
        if advance_ticks > 0:
            return None

        params = tool_payload.get("params") if isinstance(tool_payload.get("params"), dict) else {}
        keys = params.get("keys") if isinstance(params, dict) else []
        keys = keys if isinstance(keys, list) else []
        action_text = " ".join(
            str(tool_payload.get(field) or "")
            for field in (
                "intent",
                "objective",
                "expected_simulation_result",
                "plan_step",
                "plan_review",
            )
        ).lower()
        says_time_should_pass = any(
            phrase in action_text
            for phrase in (
                "advance time",
                "advance ticks",
                "let dwarves",
                "give dwarves time",
                "dwarves work",
                "execute existing",
            )
        )
        scroll_only = bool(keys) and all(str(key).startswith("STANDARDSCROLL") for key in keys)
        if says_time_should_pass or (scroll_only and "advance" in action_text):
            return (
                "Action contract mismatch: the action says to advance time or let "
                "dwarves work, but advance_ticks is 0. Set advance_ticks to a "
                "positive value such as 200, 500, 1000, or 2000; viewport scroll "
                "keys do not advance simulation time."
            )
        designation_keys = {
            "DESIGNATE_DIG",
            "DESIGNATE_CHOP",
            "DESIGNATE_CHANNEL",
            "DESIGNATE_STAIR_DOWN",
            "DESIGNATE_STAIR_UP",
            "DESIGNATE_STAIR_UPDOWN",
            "DESIGNATE_RAMP",
            "DESIGNATE_PLANTS",
        }
        completed_work_designation = (
            any(str(key) in designation_keys for key in keys)
            and sum(1 for key in keys if str(key) == "SELECT") >= 2
            and any(str(key) == "LEAVESCREEN" for key in keys)
        )
        if completed_work_designation:
            return (
                "Action contract mismatch: this key sequence completes a dig/chop/stair "
                "designation while the game is paused, but advance_ticks is 0. Set "
                "advance_ticks to 500+ so dwarves can act on the new designation before "
                "your next decision."
            )
        return None

    @staticmethod
    def _validate_screen_read(screen_read: Dict[str, Any]) -> Optional[str]:
        mode = str(screen_read.get("mode") or "").strip()
        if not mode:
            return "mode is required."
        confidence = str(screen_read.get("confidence") or "").strip().lower()
        if confidence not in {"high", "medium", "low"}:
            return "confidence must be high, medium, or low."
        evidence = screen_read.get("evidence")
        if isinstance(evidence, list):
            if not any(str(item).strip() for item in evidence):
                return "evidence must include at least one visible fact."
        elif not str(evidence or "").strip():
            return "evidence must include at least one visible fact."
        return None

    @staticmethod
    def _validate_last_action_review(last_action_review: Dict[str, Any]) -> Optional[str]:
        if "worked" not in last_action_review:
            return "worked is required; use null for the first action."
        if "should_retry_same_path" not in last_action_review:
            return "should_retry_same_path is required."
        if not isinstance(last_action_review.get("should_retry_same_path"), bool):
            return "should_retry_same_path must be true or false."
        evidence = last_action_review.get("evidence")
        if isinstance(evidence, list):
            if not any(str(item).strip() for item in evidence):
                return "evidence must include at least one verification fact."
        elif not str(evidence or "").strip():
            return "evidence must include at least one verification fact."
        return None

    @staticmethod
    def _plan_milestone_key(obs_text: str) -> Optional[str]:
        text = obs_text.lower()
        if "live ui phase: enough starter digging and building material exist" in text:
            return "construction_ready"
        if "last action changed real material stocks" in text:
            return "material_acquired"
        if re.search(r"carpenter_workshops=[1-9]", text):
            return "workshop_built"
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
    def _review_gate_warning_tool(
        required_review_error: str | None,
        *,
        forced: bool = False,
    ) -> str:
        text = str(required_review_error or "").lower()
        gate = (
            "plan_review"
            if "mandatory gameplay plan" in text
            else "memory_review"
        )
        suffix = "_forced_warning" if forced else "_warning"
        return f"{gate}_gate{suffix}"

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
        workshop_already_exists = bool(
            re.search(r"carpenter_workshops=([1-9]\d*)", text)
            or re.search(r"workshop_count=([1-9]\d*)", text)
        )
        if workshop_already_exists:
            return True
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
        tools = [self._keystroke_tool, *self._tool_manager.tool_specs()]
        tool_result_cache: Dict[str, str] = {}
        last_gate_blocked_action: Optional[Dict[str, Any]] = None
        last_gate_blocked_error: Optional[str] = None
        saw_tool_only_response = False
        action_phase_tool_names: set[str] = set()
        model = self._anthropic_model
        temperature = _request_temperature(model, self._settings.LLM_TEMP)

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

        def perception_tool_spec(name: str) -> Dict[str, Any]:
            for spec in self._tool_manager.tool_specs():
                if spec.get("name") == name:
                    return spec
            raise RuntimeError(f"Perception tool not configured: {name}")

        def collect_perception_inputs(tool_uses: List[Any]) -> Dict[str, Dict[str, Any]]:
            inputs: Dict[str, Dict[str, Any]] = {}
            for tool_use in tool_uses:
                tool_input = tool_use.input if isinstance(tool_use.input, dict) else {}
                if tool_use.name == "record_screen_read":
                    inputs["screen_read"] = dict(tool_input)
                elif tool_use.name == "review_last_action":
                    inputs["last_action_review"] = dict(tool_input)
            return inputs

        def single_perception_error(
            tool_name: str,
            tool_input: Dict[str, Any],
        ) -> Optional[str]:
            if tool_name == "record_screen_read":
                return self._validate_screen_read(tool_input)
            if tool_name == "review_last_action":
                return self._validate_last_action_review(tool_input)
            return f"Unknown perception tool: {tool_name}"

        def run_single_perception_tool(
            *,
            tool_name: str,
            result_field: str,
            prompt: str,
        ) -> Dict[str, Dict[str, Any]]:
            messages.append(
                {
                    "role": "user",
                    "content": [{"type": "text", "text": prompt}],
                }
            )
            last_prelude_error: Optional[str] = None
            for _ in range(3):
                self._rate_limit()
                client = self._client_instance()
                request_kwargs: Dict[str, Any] = {
                    "model": model,
                    "max_tokens": self._settings.LLM_MAX_TOKENS,
                    "system": self._system_prompt,
                    "tools": [perception_tool_spec(tool_name)],
                    "messages": messages,
                }
                if temperature is not None:
                    request_kwargs["temperature"] = temperature
                response = self._create_message_with_retries(client, **request_kwargs)
                _append_usage_event(
                    self._tool_events,
                    response,
                    model=model,
                    max_tokens=self._settings.LLM_MAX_TOKENS,
                    temperature=temperature,
                )
                matching_tool_use = None
                for item in response.content:
                    if getattr(item, "type", None) == "tool_use" and item.name == tool_name:
                        matching_tool_use = item
                        break

                messages.append({"role": "assistant", "content": response.content})
                if matching_tool_use is None:
                    last_prelude_error = f"Call {tool_name} before choosing keys."
                    messages.append(
                        {
                            "role": "user",
                            "content": [{"type": "text", "text": last_prelude_error}],
                        }
                    )
                    continue

                tool_input = (
                    matching_tool_use.input if isinstance(matching_tool_use.input, dict) else {}
                )
                result = self._tool_manager.handle(tool_name, tool_input)
                self._tool_events.append(
                    {
                        "tool": tool_name,
                        "input": tool_input,
                        "output": result,
                    }
                )
                error = single_perception_error(tool_name, tool_input)
                results = [tool_result(matching_tool_use, result)]
                if error is None:
                    messages.append({"role": "user", "content": results})
                    return {result_field: dict(tool_input)}
                last_prelude_error = f"{tool_name} incomplete: {error}"
                results.append({"type": "text", "text": last_prelude_error})
                messages.append({"role": "user", "content": results})
            raise RuntimeError(
                "Anthropic keystroke perception prelude failed: "
                + str(last_prelude_error)
            )

        def run_perception_prelude() -> Dict[str, Dict[str, Any]]:
            if not self._require_perception_review:
                return {}
            inputs: Dict[str, Dict[str, Any]] = {}
            inputs.update(
                run_single_perception_tool(
                    tool_name="record_screen_read",
                    result_field="screen_read",
                    prompt=(
                        "Mandatory screen-read phase: call record_screen_read now "
                        "with your current screen/menu interpretation. Do not submit "
                        "gameplay keys yet."
                    ),
                )
            )
            inputs.update(
                run_single_perception_tool(
                    tool_name="review_last_action",
                    result_field="last_action_review",
                    prompt=(
                        "Mandatory verification phase: call review_last_action now "
                        "to compare your previous action expectation to the current "
                        "observation. Use worked=null for the first action. Do not "
                        "submit gameplay keys yet."
                    ),
                )
            )
            return inputs

        def force_submit_action_after_tools() -> Dict[str, Any]:
            force_prompt = (
                f"{content}\n\n"
                "== MODEL-WRITTEN PERCEPTION FOR THIS STEP ==\n"
                f"{json.dumps(prelude_perception_inputs, ensure_ascii=True)}\n\n"
                "== ACTION-ONLY RECOVERY ==\n"
                "You already completed screen reading, last-action review, and any "
                "notebook/tool lookups for this decision step. Now call submit_action "
                "with one KEYSTROKE action. Do not call memory, wiki, planning, or "
                "perception tools. Choose the keys yourself from the current Dwarf "
                "Fortress screen and your recorded review. If your intent is to wait, "
                "advance time, or let dwarves work, set advance_ticks to a positive "
                "value such as 500, 1000, or 2000."
            )
            force_messages: List[Dict[str, Any]] = [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": force_prompt}],
                }
            ]

            def append_force_retry(
                response_content: Any,
                tool_results: List[Dict[str, Any]],
            ) -> None:
                force_messages.append({"role": "assistant", "content": response_content})
                force_messages.append({"role": "user", "content": tool_results})

            last_force_error: Exception | None = None
            for forced_attempt in range(5):
                tool_result_cache.clear()
                self._rate_limit()
                client = self._client_instance()
                request_kwargs: Dict[str, Any] = {
                    "model": model,
                    "max_tokens": self._settings.LLM_MAX_TOKENS,
                    "system": self._system_prompt,
                    "tools": [self._keystroke_tool],
                    "messages": force_messages,
                }
                if temperature is not None:
                    request_kwargs["temperature"] = temperature
                response = self._create_message_with_retries(
                    client,
                    **request_kwargs,
                )
                _append_usage_event(
                    self._tool_events,
                    response,
                    model=model,
                    max_tokens=self._settings.LLM_MAX_TOKENS,
                    temperature=temperature,
                )

                tool_payload = None
                tool_uses = []
                for item in response.content:
                    if item.type == "tool_use":
                        tool_uses.append(item)
                        action_phase_tool_names.add(str(item.name))
                        if item.name == "submit_action":
                            tool_payload = item.input

                if tool_payload is not None:
                    if not isinstance(tool_payload, dict):
                        last_force_error = ValueError(
                            "submit_action payload must be an object"
                        )
                        append_force_retry(
                            response.content,
                            tool_results_for_retry(
                                tool_uses,
                                "submit_action payload must be an object.",
                            ),
                        )
                        continue

                    if prelude_perception_inputs:
                        tool_payload = dict(tool_payload)
                        for field, value in prelude_perception_inputs.items():
                            tool_payload.setdefault(field, value)

                    if tool_payload.get("type") != "KEYSTROKE":
                        last_force_error = ValueError(
                            f"Expected KEYSTROKE action, got {tool_payload.get('type')}"
                        )
                        append_force_retry(
                            response.content,
                            tool_results_for_retry(
                                tool_uses,
                                "You must return a KEYSTROKE action.",
                            ),
                        )
                        continue

                    params = tool_payload.get("params", {})
                    keys = params.get("keys", []) if isinstance(params, dict) else []
                    if not keys or not isinstance(keys, list):
                        last_force_error = ValueError(
                            "KEYSTROKE action must have non-empty keys list"
                        )
                        append_force_retry(
                            response.content,
                            tool_results_for_retry(
                                tool_uses,
                                "KEYSTROKE action requires a non-empty keys list.",
                            ),
                        )
                        continue

                    contract_error = self._advance_ticks_contract_error(tool_payload)
                    if contract_error:
                        if "completes a dig/chop/stair designation" in contract_error:
                            tool_payload = dict(tool_payload)
                            tool_payload["advance_ticks"] = 500
                            self._tool_events.append(
                                {
                                    "tool": "advance_ticks_contract_repaired",
                                    "input": {
                                        "attempt": forced_attempt + 1,
                                        "contract_error": contract_error,
                                    },
                                    "output": (
                                        "Set advance_ticks=500 for completed "
                                        "designation during action-only recovery."
                                    ),
                                }
                            )
                        else:
                            last_force_error = ValueError(contract_error)
                            append_force_retry(
                                response.content,
                                tool_results_for_retry(tool_uses, contract_error),
                            )
                            continue

                    try:
                        action = parse_action(tool_payload)
                    except ValueError as exc:
                        last_force_error = exc
                        append_force_retry(
                            response.content,
                            tool_results_for_retry(
                                tool_uses,
                                f"Previous response invalid ({exc}). Provide valid KEYSTROKE action.",
                            ),
                        )
                        continue

                    perception_error = self._required_perception_review_error(
                        tool_payload,
                        action_phase_tool_names,
                    )
                    if perception_error:
                        last_force_error = ValueError(perception_error)
                        append_force_retry(
                            response.content,
                            tool_results_for_retry(tool_uses, perception_error),
                        )
                        continue

                    review_tool_uses = [
                        SimpleNamespace(name=name) for name in sorted(action_phase_tool_names)
                    ]
                    required_errors = [
                        error
                        for error in (
                            self._required_memory_review_error(
                                review_tool_uses,
                                obs_text,
                                tool_payload,
                            ),
                            self._required_plan_review_error(review_tool_uses, obs_text),
                        )
                        if error
                    ]
                    required_review_error = (
                        "\n".join(required_errors) if required_errors else None
                    )
                    if required_review_error:
                        warning_tool = self._review_gate_warning_tool(
                            required_review_error,
                            forced=True,
                        )
                        self._tool_events.append(
                            {
                                "tool": warning_tool,
                                "input": {
                                    "attempt": forced_attempt + 1,
                                    "required_review_error": required_review_error,
                                    "prior_tool_names": sorted(action_phase_tool_names),
                                },
                                "output": (
                                    "Allowed action-only recovery despite unmet "
                                    "review gate; recovery can only call submit_action."
                                ),
                            }
                        )
                        milestone_key = self._plan_milestone_key(obs_text)
                        if milestone_key is not None:
                            self._reviewed_plan_milestones.add(milestone_key)

                    self._tool_events.append(
                        {
                            "tool": "submit_action_forced_after_tools",
                            "input": {
                                "attempt": forced_attempt + 1,
                                "prior_tool_names": sorted(action_phase_tool_names),
                            },
                            "output": "Accepted model submit_action after action-only recovery.",
                        }
                    )
                    self._pending_observation = obs_text
                    self._pending_action = action
                    self._completed_actions += 1
                    return action

                last_force_error = ValueError(
                    "Model did not use submit_action in action-only recovery"
                )
                if tool_uses:
                    append_force_retry(
                        response.content,
                        tool_results_for_retry(
                            tool_uses,
                            "Only submit_action is available now; send one KEYSTROKE action.",
                        ),
                    )
                    continue

                force_messages.append({"role": "assistant", "content": response.content})
                force_messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Use submit_action now with one KEYSTROKE action.",
                            }
                        ],
                    }
                )

            raise RuntimeError(
                "Anthropic keystroke action-only recovery failed: "
                + str(last_force_error)
            )

        prelude_perception_inputs = run_perception_prelude()

        for attempt_index in range(5):
            tool_result_cache.clear()
            self._rate_limit()
            client = self._client_instance()
            request_kwargs: Dict[str, Any] = {
                "model": model,
                "max_tokens": self._settings.LLM_MAX_TOKENS,
                "system": self._system_prompt,
                "tools": tools,
                "messages": messages,
            }
            if temperature is not None:
                request_kwargs["temperature"] = temperature
            response = self._create_message_with_retries(
                client,
                **request_kwargs,
            )
            _append_usage_event(
                self._tool_events,
                response,
                model=model,
                max_tokens=self._settings.LLM_MAX_TOKENS,
                temperature=temperature,
            )

            tool_payload = None
            tool_uses = []
            perception_inputs: Dict[str, Dict[str, Any]] = {}
            for item in response.content:
                if item.type == "tool_use":
                    tool_uses.append(item)
                    action_phase_tool_names.add(str(item.name))
                    tool_input = item.input if isinstance(item.input, dict) else {}
                    if item.name == "record_screen_read":
                        perception_inputs["screen_read"] = dict(tool_input)
                    elif item.name == "review_last_action":
                        perception_inputs["last_action_review"] = dict(tool_input)
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
                if isinstance(tool_payload, dict) and (
                    prelude_perception_inputs or perception_inputs
                ):
                    tool_payload = dict(tool_payload)
                    combined_perception_inputs = {
                        **prelude_perception_inputs,
                        **perception_inputs,
                    }
                    for field, value in combined_perception_inputs.items():
                        tool_payload.setdefault(field, value)

                # Validate it's a KEYSTROKE action before applying planning gates.
                # If the model spends retries on notebook tools but never resubmits,
                # we can still fall back to this last valid candidate without
                # crashing the live run.
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
                keys = params.get("keys", []) if isinstance(params, dict) else []
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

                contract_error = self._advance_ticks_contract_error(tool_payload)
                if contract_error:
                    last_error = ValueError(contract_error)
                    append_tool_retry(
                        response.content,
                        tool_results_for_retry(tool_uses, contract_error),
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

                perception_error = self._required_perception_review_error(
                    tool_payload,
                    {str(getattr(tool_use, "name", "")) for tool_use in tool_uses},
                )
                if perception_error:
                    last_error = ValueError(perception_error)
                    append_tool_retry(
                        response.content,
                        tool_results_for_retry(tool_uses, perception_error),
                    )
                    continue

                review_tool_uses = [
                    SimpleNamespace(name=name) for name in sorted(action_phase_tool_names)
                ]
                required_errors = [
                    error
                    for error in (
                        self._required_memory_review_error(
                            review_tool_uses,
                            obs_text,
                            tool_payload,
                        ),
                        self._required_plan_review_error(review_tool_uses, obs_text),
                    )
                    if error
                ]
                required_review_error = "\n".join(required_errors) if required_errors else None
                if required_review_error and attempt_index < 3:
                    last_gate_blocked_action = action
                    last_gate_blocked_error = required_review_error
                    last_error = ValueError(required_review_error)
                    append_tool_retry(
                        response.content,
                        tool_results_for_retry(tool_uses, required_review_error),
                    )
                    continue
                if required_review_error:
                    warning_tool = self._review_gate_warning_tool(
                        required_review_error,
                    )
                    self._tool_events.append(
                        {
                            "tool": warning_tool,
                            "input": {
                                "attempt": attempt_index + 1,
                                "required_review_error": required_review_error,
                            },
                            "output": "Allowed action after bounded memory-review retries.",
                        }
                    )
                    milestone_key = self._plan_milestone_key(obs_text)
                    if milestone_key is not None:
                        self._reviewed_plan_milestones.add(milestone_key)

                self._pending_observation = obs_text
                self._pending_action = action
                self._completed_actions += 1
                return action

            if tool_uses:
                saw_tool_only_response = True
                last_error = ValueError("Model used tools but did not submit an action")
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

        if self._require_perception_review:
            if saw_tool_only_response:
                return force_submit_action_after_tools()
            raise RuntimeError(f"Anthropic keystroke perception contract failed: {last_error}")

        if last_gate_blocked_action is not None:
            warning_tool = self._review_gate_warning_tool(
                last_gate_blocked_error,
            )
            self._tool_events.append(
                {
                    "tool": warning_tool,
                    "input": {
                        "attempt": "fallback",
                        "required_review_error": last_gate_blocked_error,
                    },
                    "output": (
                        "Allowed last valid action after bounded review retries because "
                        "the model stopped submitting actions."
                    ),
                }
            )
            self._pending_observation = obs_text
            self._pending_action = last_gate_blocked_action
            self._completed_actions += 1
            return last_gate_blocked_action

        if saw_tool_only_response:
            fallback_action = parse_action(
                {
                    "type": "KEYSTROKE",
                    "params": {"keys": ["LEAVESCREEN"]},
                    "intent": (
                        "fallback: exit one menu after the model used notebook tools "
                        "but did not submit an action"
                    ),
                    "objective": "recover from missing submit_action",
                    "expected_visible_result": "one menu closes or main view remains visible",
                    "expected_simulation_result": "none; no game ticks advance",
                    "memory_update": "model made tool-only responses without submit_action",
                    "plan_step": "recover from missing submit_action",
                    "plan_review": "bounded retry fallback; no model action was submitted",
                    "advance_ticks": 0,
                }
            )
            self._tool_events.append(
                {
                    "tool": "submit_action_fallback",
                    "input": {"last_error": str(last_error)},
                    "output": "Submitted LEAVESCREEN after bounded tool-only retries.",
                }
            )
            self._pending_observation = obs_text
            self._pending_action = fallback_action
            self._completed_actions += 1
            return fallback_action

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
register_agent(
    "anthropic-keystroke-plan-review",
    lambda: AnthropicKeystrokeAgent(
        system_prompt=KEYSTROKE_PLAN_REVIEW_SYSTEM_PROMPT,
        require_memory_review=True,
        require_plan_review=True,
        plan_review_interval=5,
    ),
)
register_agent(
    "anthropic-keystroke-perception-review",
    lambda: AnthropicKeystrokeAgent(
        system_prompt=KEYSTROKE_PERCEPTION_REVIEW_SYSTEM_PROMPT,
        require_memory_review=True,
        require_plan_review=True,
        require_perception_review=True,
        plan_review_interval=5,
    ),
)
register_agent(
    "anthropic-keystroke-perception-review-opus",
    lambda: AnthropicKeystrokeAgent(
        system_prompt=KEYSTROKE_PERCEPTION_REVIEW_SYSTEM_PROMPT,
        require_memory_review=True,
        require_plan_review=True,
        require_perception_review=True,
        plan_review_interval=5,
        model_override=get_settings().ANTHROPIC_OPUS_MODEL,
    ),
)


__all__ = [
    "AnthropicActionAgent",
    "AnthropicDigFirstAgent",
    "AnthropicFortressPlanAgent",
    "AnthropicKeystrokeAgent",
    "DIG_FIRST_SYSTEM_PROMPT",
    "FORTRESS_PLAN_SYSTEM_PROMPT",
    "KEYSTROKE_PERCEPTION_REVIEW_SYSTEM_PROMPT",
    "KEYSTROKE_SYSTEM_PROMPT",
    "KEYSTROKE_POI_REVIEW_SYSTEM_PROMPT",
    "KEYSTROKE_PLAN_REVIEW_SYSTEM_PROMPT",
]
