"""Versioned keyboard-only response contract; no native execution or shortcuts."""

from __future__ import annotations

from copy import deepcopy

from ..env.keystroke_exec import VALID_KEYS
from ..env.screen_observation import RAW_PROFILE, raw_screen

CONTROL_PROFILE = "native_keyboard/v1"
OBSERVATION_PROFILE = RAW_PROFILE


def response_schema(*, max_advance_ticks: int) -> dict:
    if type(max_advance_ticks) is not int or not 0 <= max_advance_ticks <= 2500:
        raise ValueError("Invalid keyboard simulation bound")
    properties = {
        "type": {"type": "string", "enum": ["KEYSTROKE"]},
        "params": {
            "type": "object",
            "properties": {
                "keys": {
                    "type": "array",
                    "items": {"type": "string", "enum": sorted(VALID_KEYS)},
                    "maxItems": 100,
                }
            },
            "required": ["keys"],
            "additionalProperties": False,
        },
        "advance_ticks": {"type": "integer", "minimum": 0, "maximum": max_advance_ticks},
        "intent": {"type": "string"},
        "memory_update": {"type": "string"},
    }
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def parse_response(payload: object, *, max_advance_ticks: int) -> dict:
    """Validate without coercing keys, inventing WAIT, or choosing a game action."""
    schema = response_schema(max_advance_ticks=max_advance_ticks)
    if not isinstance(payload, dict) or set(payload) != set(schema["required"]):
        raise ValueError("Keyboard response fields differ from the declared contract")
    params = payload.get("params")
    if payload.get("type") != "KEYSTROKE" or not isinstance(params, dict):
        raise ValueError("Standard input requires KEYSTROKE, never a DFHack shortcut")
    keys = params.get("keys")
    if (
        set(params) != {"keys"}
        or not isinstance(keys, list)
        or len(keys) > 100
        or any(not isinstance(key, str) or key not in VALID_KEYS for key in keys)
    ):
        raise ValueError("Keyboard keys must be supported native interface events")
    ticks = payload.get("advance_ticks")
    if type(ticks) is not int or not 0 <= ticks <= max_advance_ticks:
        raise ValueError("Keyboard advance exceeds the declared simulation bound")
    if any(not isinstance(payload[key], str) for key in ("intent", "memory_update")):
        raise ValueError("Keyboard notes must be strings; empty notes are allowed")
    return deepcopy(payload)


def screen_observation(screen: object) -> dict:
    """Preserve the full captured grid and colors, without adding internal state.

    Dimensions are observations, not requested render sizes. Resizing the native
    runtime is a separate operation and must be verified through a new capture.
    """
    return raw_screen(screen)
