"""Campaign keyboard dispatch with per-event native receipts and no retries."""

from __future__ import annotations

import time
from pathlib import Path

from ..dfhack_backend import _hook_path
from ..dfhack_exec import DFHackError, run_lua_file
from .keystroke_exec import VALID_KEYS

KEYBOARD_CONTROL_PROFILE = "native_keyboard/v1"
HELPER_CONTROL_PROFILE = "dfhack_shortcuts/v1"
NATIVE_SCHEMA = "fortgym.campaign-keyboard-native/v1"


def execute_campaign_keys(
    keys: object, *, expected_dfroot: Path, year: object, year_tick: object
) -> dict:
    """Send up to 100 chosen events, holding zero game ticks between them.

    Receipt success means the input function returned, not that its requested
    gameplay effect occurred. Frame freshness is not inferred from the small
    inter-event delay; native diagnostics must inspect the resulting screens.
    """
    result: dict = {
        "schema_version": "fortgym.campaign-keyboard-execution/v1",
        "ok": False,
        "command_mutation": "not_attempted",
        "keys_confirmed": 0,
        "keys_sent": 0,
        "native_receipts": [],
        "frame_freshness": "not_verified",
        "simulation_policy": "paused_inputs_then_explicit_advance_ticks",
    }

    def finish(error: str | None = None) -> dict:
        result["ok"] = error is None
        if error is not None:
            result["error"] = error
        return {"accepted": result["ok"], "why": error, "result": result}

    if (
        not isinstance(keys, list)
        or len(keys) > 100
        or any(not isinstance(key, str) or key not in VALID_KEYS for key in keys)
        or type(year) is not int
        or year < 0
        or type(year_tick) is not int
        or not 0 <= year_tick < 403200
    ):
        return finish("Invalid native keyboard keys or calendar")
    root = str(expected_dfroot.resolve())
    hook = _hook_path("campaign_keyboard_v1.lua")
    boundary = (root, str(year), str(year_tick))
    save_name = ""
    for key in [None, *keys]:
        mode, arguments = ("probe", keys) if key is None else ("key", [key])
        try:
            receipt: dict = run_lua_file(hook, mode, *boundary, save_name, *arguments, timeout=5)
        except (DFHackError, OSError) as exc:
            if mode == "key":
                result.update(command_mutation="unknown", keys_sent=None)
            return finish(str(exc))
        result["native_receipts"].append(receipt)
        if not isinstance(receipt, dict) or receipt.get("schema_version") != NATIVE_SCHEMA:
            if mode == "key":
                result.update(command_mutation="unknown", keys_sent=None)
            return finish("Malformed native keyboard receipt")
        if receipt.get("ok") is not True:
            if mode == "key" and (
                receipt.get("command_mutation") != "not_attempted"
                or type(receipt.get("keys_sent")) is not int
                or receipt["keys_sent"] != 0
            ):
                result.update(command_mutation="unknown", keys_sent=None)
            elif result["keys_confirmed"]:
                result["command_mutation"] = "partial"
            return finish(str(receipt.get("error") or "Native keyboard input failed"))
        before, after = receipt.get("before"), receipt.get("after")
        if not isinstance(before, dict) or not isinstance(after, dict):
            if mode == "key":
                result.update(command_mutation="unknown", keys_sent=None)
            return finish("Native keyboard receipt is missing its boundary")
        expected_count = 0 if mode == "probe" else 1
        expected_mutation = "not_attempted" if mode == "probe" else "completed"
        valid = (
            receipt.get("mode") == mode
            and type(receipt.get("keys_sent")) is int
            and receipt["keys_sent"] == expected_count
            and receipt.get("command_mutation") == expected_mutation
            and (mode == "probe" or receipt.get("key") == key)
        )
        for state in (before, after):
            valid = valid and (
                isinstance(state, dict)
                and state.get("dfroot") == root
                and type(state.get("year")) is int
                and state["year"] == year
                and type(state.get("year_tick")) is int
                and state["year_tick"] == year_tick
                and state.get("paused") is True
                and isinstance(state.get("save_name"), str)
                and bool(state["save_name"])
            )
        valid = valid and before["save_name"] == after["save_name"]
        valid = valid and (mode == "probe" or before["save_name"] == save_name)
        if not valid:
            if mode == "key":
                result.update(command_mutation="unknown", keys_sent=None)
            return finish("Native keyboard receipt does not establish the requested boundary")
        save_name = before["save_name"]
        if mode == "key":
            result["keys_confirmed"] += 1
            result["keys_sent"] = result["keys_confirmed"]
            result["command_mutation"] = "completed"
            # Preserve the existing sender's UI cadence without advancing world
            # time. No key is selected, replaced, or retried by the executor.
            time.sleep(0.05)
    return finish()
