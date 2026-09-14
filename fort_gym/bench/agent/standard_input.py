"""Versioned keyboard-only response contract; no native execution or shortcuts."""

from __future__ import annotations

from copy import deepcopy

from ..env.native_key_catalog import LEGACY_PROFILE, keys_for_profile
from ..env.screen_observation import RAW_PROFILE, raw_screen
from ..env.workshop_job_profile import CONTROL_PROFILE as WORKSHOP_PROFILE

CONTROL_PROFILE = LEGACY_PROFILE
OBSERVATION_PROFILE = RAW_PROFILE


def response_schema(*, max_advance_ticks: int, control_profile: str = CONTROL_PROFILE) -> dict:
    if control_profile == WORKSHOP_PROFILE:
        from .workshop_input import response_schema as workshop_schema

        return workshop_schema(max_advance_ticks=max_advance_ticks)
    if type(max_advance_ticks) is not int or not 0 <= max_advance_ticks <= 2500:
        raise ValueError("Invalid keyboard simulation bound")
    allowed_keys = keys_for_profile(control_profile)
    # v2 has 1613 names: too many for the structured-output enum limit (1000).
    # Keep the wire shape strict and validate membership locally before dispatch.
    key_item: dict = {"type": "string"}
    if control_profile == LEGACY_PROFILE:
        key_item["enum"] = sorted(allowed_keys)
    properties = {
        "type": {"type": "string", "enum": ["KEYSTROKE"]},
        "params": {
            "type": "object",
            "properties": {
                "keys": {
                    "type": "array",
                    "items": key_item,
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


def parse_envelope(
    payload: object, *, max_advance_ticks: int, control_profile: str = CONTROL_PROFILE
) -> dict:
    """Validate the response shape and limits without authorizing its key names."""
    if control_profile == WORKSHOP_PROFILE:
        from .workshop_input import parse_envelope as workshop_envelope

        return workshop_envelope(payload, max_advance_ticks=max_advance_ticks)
    schema = response_schema(max_advance_ticks=max_advance_ticks, control_profile=control_profile)
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
        or any(not isinstance(key, str) for key in keys)
    ):
        raise ValueError("Keyboard keys must be supported native interface events")
    ticks = payload.get("advance_ticks")
    if type(ticks) is not int or not 0 <= ticks <= max_advance_ticks:
        raise ValueError("Keyboard advance exceeds the declared simulation bound")
    if any(not isinstance(payload[key], str) for key in ("intent", "memory_update")):
        raise ValueError("Keyboard notes must be strings; empty notes are allowed")
    return deepcopy(payload)


def parse_response(
    payload: object, *, max_advance_ticks: int, control_profile: str = CONTROL_PROFILE
) -> dict:
    """Validate without coercing keys, inventing WAIT, or choosing a game action."""
    if control_profile == WORKSHOP_PROFILE:
        from .workshop_input import parse_response as workshop_response

        return workshop_response(payload, max_advance_ticks=max_advance_ticks)
    action = parse_envelope(
        payload, max_advance_ticks=max_advance_ticks, control_profile=control_profile
    )
    allowed_keys = keys_for_profile(control_profile)
    if any(key not in allowed_keys for key in action["params"]["keys"]):
        raise ValueError("Keyboard keys must be supported native interface events")
    return action


def screen_observation(screen: object) -> dict:
    """Preserve the full captured grid and colors, without adding internal state.

    Dimensions are observations, not requested render sizes. Resizing the native
    runtime is a separate operation and must be verified through a new capture.
    """
    return raw_screen(screen)
