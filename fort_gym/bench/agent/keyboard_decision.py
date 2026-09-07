"""One model-selected keyboard decision from a declared screen-only observation.

This connects screen capture to the subscription transport and validates its
response. It intentionally does not dispatch game commands or implement campaign
checkpoints: those remain owned by the native campaign controller.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

from .codex_transport import CodexTransportError, request_decision
from .standard_input import (
    CONTROL_PROFILE,
    OBSERVATION_PROFILE,
    parse_response,
    response_schema,
    screen_observation,
)

INSTRUCTIONS = """You are playing Dwarf Fortress Classic 0.47.05.
Develop a functioning fortress, sustain its population, and keep playing into year
two and beyond. Choose your own strategy; no mandatory build order is imposed.

Your controls are native game-interface key events. Navigate the actual menus to
designate work, place buildings, and add workshop jobs. Direct DFHack build/order
shortcuts are not available in this condition. The action executor, not you,
handles the transport of your chosen keys. Do not call coding or terminal tools.

The captured screen uses column-major tiles. Each tile is [character, foreground,
background], with Classic CP437 character codes. Color carries selection/cursor
information. Width and height describe the actual captured grid. No hidden terrain
or internal fortress metrics are supplied. Missing information is unknown.

Return one KEYSTROKE response matching the supplied response contract. An empty
keys list requests only simulation advancement. advance_ticks is the requested
game time after the input; use zero when you want to inspect the next menu without
advancing time. intent and memory_update may be empty strings. Queuing work does
not complete it: dwarves still need inputs, labor, and game time.
"""


def request_keyboard_decision(
    screen: dict,
    *,
    executable: Path,
    artifact_root: Path,
    allowance_check: Callable[[], dict],
    max_advance_ticks: int = 2000,
    memory: str = "",
    timeout_seconds: float = 180,
) -> dict:
    if not isinstance(memory, str):
        raise ValueError("Agent memory must be text")
    observation = screen_observation(screen)
    schema = response_schema(max_advance_ticks=max_advance_ticks)
    observation_json = json.dumps(observation, allow_nan=False, sort_keys=True)
    prompt = (
        INSTRUCTIONS
        + "\nResponse contract:\n"
        + json.dumps(schema, sort_keys=True)
        + "\nYour retained memory:\n"
        + memory
        + "\nCurrent captured screen:\n"
        + observation_json
    )
    receipt = request_decision(
        prompt,
        schema,
        executable=executable,
        artifact_root=artifact_root,
        allowance_check=allowance_check,
        timeout_seconds=timeout_seconds,
    )
    action, error = None, None
    try:
        action = parse_response(receipt["response"], max_advance_ticks=max_advance_ticks)
    except ValueError as exc:
        error = str(exc)
    result = {
        "schema_version": "fortgym.keyboard-decision/v1",
        "control_profile": CONTROL_PROFILE,
        "observation_profile": OBSERVATION_PROFILE,
        "screen_sha256": hashlib.sha256(observation_json.encode()).hexdigest(),
        "screen_width": observation["width"],
        "screen_height": observation["height"],
        "action": action,
        "action_grammar_valid": action is not None,
        "native_action_dispatched": False,
        "error": error,
        "transport_receipt": receipt,
    }
    path = Path(receipt["run_directory"]) / "keyboard-decision.json"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, indent=2, allow_nan=False) + "\n")
    if error is not None:
        raise CodexTransportError("Model response failed the keyboard contract", result)
    return result
