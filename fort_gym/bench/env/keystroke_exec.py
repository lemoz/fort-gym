"""Keystroke execution via DFHack devel/send-key command."""

from __future__ import annotations

import subprocess
import time
from typing import Dict, List, Tuple

from ..config import dfhack_cmd
from ..dfhack_exec import run_lua_expr


# Common interface keys for Dwarf Fortress v0.47.05
# Full list available via: dfhack-run lua "@df.interface_key"
VALID_KEYS: set[str] = {
    # Navigation
    "CURSOR_UP", "CURSOR_DOWN", "CURSOR_LEFT", "CURSOR_RIGHT",
    "CURSOR_UPLEFT", "CURSOR_UPRIGHT", "CURSOR_DOWNLEFT", "CURSOR_DOWNRIGHT",
    "CURSOR_UP_FAST", "CURSOR_DOWN_FAST", "CURSOR_LEFT_FAST", "CURSOR_RIGHT_FAST",
    "CURSOR_UPLEFT_FAST", "CURSOR_UPRIGHT_FAST", "CURSOR_DOWNLEFT_FAST", "CURSOR_DOWNRIGHT_FAST",
    "CURSOR_UP_Z", "CURSOR_DOWN_Z", "CURSOR_UP_Z_AUX", "CURSOR_DOWN_Z_AUX",

    # Selection and confirmation
    "SELECT", "SEC_SELECT", "DESELECT", "SELECT_ALL", "DESELECT_ALL",
    "LEAVESCREEN", "LEAVESCREEN_ALL",
    "MENU_CONFIRM",

    # Scrolling
    "STANDARDSCROLL_UP", "STANDARDSCROLL_DOWN", "STANDARDSCROLL_LEFT", "STANDARDSCROLL_RIGHT",
    "STANDARDSCROLL_PAGEUP", "STANDARDSCROLL_PAGEDOWN",
    "SECONDSCROLL_UP", "SECONDSCROLL_DOWN", "SECONDSCROLL_PAGEUP", "SECONDSCROLL_PAGEDOWN",

    # Tab/options
    "CHANGETAB", "SEC_CHANGETAB",
    "OPTION1", "OPTION2", "OPTION3", "OPTION4", "OPTION5",
    "OPTION6", "OPTION7", "OPTION8", "OPTION9", "OPTION10",

    # Main menus (d, b, i, p, etc.)
    "D_DESIGNATE", "D_BUILDJOB", "D_CIVZONE", "D_STOCKPILES",
    "D_BUILDINGLIST", "D_UNITLIST", "D_JOBLIST", "D_MILITARY",
    "D_NOBLES", "D_ANNOUNCE", "D_ORDERS", "D_SQUADS", "D_BURROWS",
    "D_HAULING", "D_LOOK", "D_VIEWUNIT", "D_STATUS", "D_ARTLIST",
    "D_LOCATIONS", "D_HOT_KEYS", "D_MOVIES", "D_REPORTS", "D_NOTE",

    # Designate submenu
    "DESIGNATE_DIG", "DESIGNATE_DIG_REMOVE_STAIRS_RAMPS",
    "DESIGNATE_CHANNEL", "DESIGNATE_STAIR_UP", "DESIGNATE_STAIR_DOWN", "DESIGNATE_STAIR_UPDOWN",
    "DESIGNATE_RAMP", "DESIGNATE_CHOP", "DESIGNATE_PLANTS",
    "DESIGNATE_SMOOTH", "DESIGNATE_ENGRAVE", "DESIGNATE_FORTIFY",
    "DESIGNATE_TRACK", "DESIGNATE_TOGGLE_ENGRAVING",
    "DESIGNATE_TRAFFIC", "DESIGNATE_TRAFFIC_HIGH", "DESIGNATE_TRAFFIC_NORMAL",
    "DESIGNATE_TRAFFIC_LOW", "DESIGNATE_TRAFFIC_RESTRICTED",
    "DESIGNATE_UNDO", "DESIGNATE_REMOVE_CONSTRUCTION",
    "DESIGNATE_BITEM", "DESIGNATE_CLAIM", "DESIGNATE_UNCLAIM",
    "DESIGNATE_MELT", "DESIGNATE_NO_MELT", "DESIGNATE_DUMP", "DESIGNATE_NO_DUMP",
    "DESIGNATE_HIDE", "DESIGNATE_NO_HIDE",
    "DESIGNATE_STANDARD_MARKER", "DESIGNATE_MINE_MODE", "DESIGNATE_TOGGLE_MARKER",

    # Build submenu
    "BUILDJOB_DOOR", "BUILDJOB_FLOODGATE", "BUILDJOB_HATCH",
    "BUILDJOB_WALL", "BUILDJOB_FLOOR", "BUILDJOB_RAMP",
    "BUILDJOB_BRIDGE", "BUILDJOB_WELL", "BUILDJOB_STAIRS_UP",
    "BUILDJOB_STAIRS_DOWN", "BUILDJOB_STAIRS_UPDOWN",
    "BUILDJOB_WORKSHOP", "BUILDJOB_FURNACE", "BUILDJOB_CONSTRUCTION",
    "BUILDJOB_SIEGE", "BUILDJOB_TRAP", "BUILDJOB_MACHINE",
    "BUILDJOB_BED", "BUILDJOB_CHAIR", "BUILDJOB_TABLE",
    "BUILDJOB_COFFIN", "BUILDJOB_STATUE", "BUILDJOB_ARMORSTAND",
    "BUILDJOB_WEAPONRACK", "BUILDJOB_CABINET", "BUILDJOB_CHEST",

    # Workshop types
    "HOTKEY_MAKE_CARPENTER", "HOTKEY_MAKE_CRAFTSMAN", "HOTKEY_MAKE_MASON",
    "HOTKEY_MAKE_METALSMITH", "HOTKEY_MAKE_JEWELER", "HOTKEY_MAKE_MECHANIC",
    "HOTKEY_MAKE_STILL", "HOTKEY_MAKE_KITCHEN", "HOTKEY_MAKE_FARMER",
    "HOTKEY_MAKE_BUTCHER", "HOTKEY_MAKE_TANNER", "HOTKEY_MAKE_LEATHER",
    "HOTKEY_MAKE_CLOTHIER", "HOTKEY_MAKE_DYER", "HOTKEY_MAKE_LOOM",
    "HOTKEY_MAKE_QUERN", "HOTKEY_MAKE_MILL", "HOTKEY_MAKE_SIEGE",
    "HOTKEY_MAKE_BOWYER", "HOTKEY_MAKE_ASHERY",

    # Zone controls
    "CIVZONE_WATER_PIT", "CIVZONE_WATER_POND", "CIVZONE_GATHER",
    "CIVZONE_HOSPITAL", "CIVZONE_DUMP", "CIVZONE_FISH",
    "CIVZONE_MEETING_AREA", "CIVZONE_ACTIVE", "CIVZONE_REMOVE",

    # Stockpile controls
    "STOCKPILE_ANIMAL", "STOCKPILE_FOOD", "STOCKPILE_WEAPON",
    "STOCKPILE_ARMOR", "STOCKPILE_AMMO", "STOCKPILE_FURNITURE",
    "STOCKPILE_CORPSE", "STOCKPILE_REFUSE", "STOCKPILE_STONE",
    "STOCKPILE_WOOD", "STOCKPILE_CLOTH", "STOCKPILE_GEM",
    "STOCKPILE_BAR", "STOCKPILE_FINISHED", "STOCKPILE_CUSTOM",

    # Manager/orders
    "MANAGER_NEW_ORDER", "MANAGER_REMOVE",

    # Squad controls
    "D_SQUADS_KILL", "D_SQUADS_MOVE", "D_SQUADS_STATION",
    "D_SQUADS_PATROL", "D_SQUADS_CANCEL_ORDERS",

    # Misc
    "PAUSE", "MOVIE_RECORD", "MOVIE_PLAY", "MOVIE_SAVE", "MOVIE_LOAD",
    "ZOOM_IN", "ZOOM_OUT", "ZOOM_TOGGLE", "ZOOM_RESET",
    "FPS_UP", "FPS_DOWN",
    "TOGGLE_FULLSCREEN", "HELP", "OPTIONS",
    # Embark/location setup
    "SETUP_EMBARK",

    # Extended character input (ASCII codes as STRING_A000-STRING_A127)
    # These allow typing arbitrary characters
}

# Add STRING_A000 through STRING_A127 for character input
for i in range(128):
    VALID_KEYS.add(f"STRING_A{i:03d}")


class KeystrokeError(Exception):
    """Error during keystroke execution."""
    pass


def _get_viewscreen_type() -> str | None:
    """Best-effort current viewscreen type for context-aware key translation."""
    try:
        out = run_lua_expr(
            "local v=dfhack.gui.getCurViewscreen(); print(v._type or '')",
            timeout=0.5,
        )
    except Exception:
        return None
    out = out.strip()
    if not out:
        return None
    # Typical form: "<type: viewscreen_choose_start_sitest>"
    if out.startswith("<type:") and out.endswith(">"):
        return out[len("<type:") : -1].strip()
    return out


def _translate_key(key: str, screen_type: str | None) -> str:
    """Translate raw keys into DF interface keys based on current screen."""
    if screen_type == "viewscreen_choose_start_sitest":
        # Embark site selection uses SETUP_EMBARK, not raw 'e'
        if key in {"STRING_A101", "CUSTOM_E"}:
            return "SETUP_EMBARK"
    return key


def send_key(key: str, timeout: float = 5.0) -> bool:
    """Send a single keystroke to DFHack.

    Args:
        key: The interface_key name (e.g., "D_DESIGNATE", "CURSOR_UP")
        timeout: Maximum time to wait for command

    Returns:
        True if successful, False if key is invalid

    Raises:
        KeystrokeError: If DFHack command fails
    """
    try:
        key = _translate_key(key, _get_viewscreen_type())
        if key not in VALID_KEYS:
            return False
        cmd = dfhack_cmd("devel/send-key", key)
        subprocess.check_call(cmd, timeout=timeout, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.05)  # Small delay for game to process
        return True
    except subprocess.TimeoutExpired as exc:
        raise KeystrokeError(f"Keystroke timeout: {key}") from exc
    except subprocess.CalledProcessError as exc:
        raise KeystrokeError(f"Keystroke failed: {key} (exit {exc.returncode})") from exc


def send_sequence(keys: List[str], delay: float = 0.05) -> Tuple[int, str]:
    """Send a sequence of keystrokes to DFHack.

    Args:
        keys: List of interface_key names
        delay: Delay between keystrokes (seconds)

    Returns:
        Tuple of (keys_sent, error_message_or_empty)
        If error_message is non-empty, keys_sent is the count before failure.
    """
    if not keys:
        return 0, ""

    screen_type = _get_viewscreen_type()
    for i, key in enumerate(keys):
        key = _translate_key(key, screen_type)
        if key not in VALID_KEYS:
            return i, f"Invalid key at position {i}: {key}"

        try:
            cmd = dfhack_cmd("devel/send-key", key)
            subprocess.check_call(cmd, timeout=5.0, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if delay > 0:
                time.sleep(delay)
        except subprocess.TimeoutExpired:
            return i, f"Timeout at key {i}: {key}"
        except subprocess.CalledProcessError as exc:
            return i, f"Failed at key {i}: {key} (exit {exc.returncode})"

    return len(keys), ""


def execute_keystroke_action(keys: List[str]) -> Dict[str, object]:
    """Execute a KEYSTROKE action and return result dict.

    Args:
        keys: List of interface_key names

    Returns:
        Dict with 'ok', 'keys_sent', and optionally 'error'
    """
    if not isinstance(keys, list):
        return {"ok": False, "error": "keys must be a list", "keys_sent": 0}

    if len(keys) > 100:
        return {"ok": False, "error": "Too many keys (max 100)", "keys_sent": 0}

    keys_sent, error = send_sequence(keys)

    result: Dict[str, object] = {
        "ok": error == "",
        "keys_sent": keys_sent,
    }
    if error:
        result["error"] = error

    return result


def char_to_key(char: str) -> str:
    """Convert a single character to its STRING_A### key name.

    Args:
        char: A single ASCII character

    Returns:
        The STRING_A### key name (e.g., 'a' -> 'STRING_A097')
    """
    if len(char) != 1:
        raise ValueError("Expected single character")
    code = ord(char)
    if code > 127:
        raise ValueError(f"Non-ASCII character: {char}")
    return f"STRING_A{code:03d}"


def string_to_keys(text: str) -> List[str]:
    """Convert a string to a list of STRING_A### keys.

    Args:
        text: ASCII string to convert

    Returns:
        List of STRING_A### key names
    """
    return [char_to_key(c) for c in text]


__all__ = [
    "VALID_KEYS",
    "KeystrokeError",
    "send_key",
    "send_sequence",
    "execute_keystroke_action",
    "char_to_key",
    "string_to_keys",
]
