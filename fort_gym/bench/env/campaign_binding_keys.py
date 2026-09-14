"""One pinned displayed key becomes one simultaneous native event-set input."""

from __future__ import annotations

from pathlib import Path
import time

from ..dfhack_backend import _hook_path
from ..dfhack_exec import DFHackError, run_lua_file
from .display_key_catalog import BINDING_PROFILE, BINDINGS_SHA256, DISPLAY_KEYS, binding_event
from .keyboard_bindings import MAX_FILE_BYTES, BindingIndex, parse_bindings
from .native_key_catalog import NATIVE_KEYS, NATIVE_PROFILE


def read_binding_index(root: Path) -> BindingIndex:
    path = root / "data/init/interface.txt"
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_FILE_BYTES:
        raise ValueError("A bounded regular interface binding file is required")
    with path.open("rb") as stream:
        index = parse_bindings(stream.read(MAX_FILE_BYTES + 1))
    if index.sha256 != BINDINGS_SHA256:
        raise ValueError("Runtime binding file differs from the declared profile")
    if set(index.repeat_policy) - NATIVE_KEYS:
        raise ValueError("Runtime bindings contain unknown native events")
    options = set(index.characters) | {f"SYM:{mask}:{name}" for mask, name in index.symbols}
    if options != DISPLAY_KEYS:
        raise ValueError("Runtime keyboard capabilities differ from the declared profile")
    return index


def execute_binding_keys(
    keys: object, *, expected_dfroot: Path, year: object, year_tick: object
) -> dict:
    from .campaign_keyboard import execute_campaign_keys

    result: dict = {
        "schema_version": "fortgym.campaign-binding-execution/v1",
        "ok": False,
        "control_profile": BINDING_PROFILE,
        "bindings_sha256": BINDINGS_SHA256,
        "command_mutation": "not_attempted",
        "keys_sent": 0,
        "keys_confirmed": 0,
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
        or any(not isinstance(key, str) or key not in DISPLAY_KEYS for key in keys)
        or type(year) is not int
        or year < 0
        or type(year_tick) is not int
        or not 0 <= year_tick < 403200
    ):
        return finish("Invalid displayed keyboard keys or calendar")
    root = expected_dfroot.resolve()
    try:
        index = read_binding_index(root)
        batches = [list(index.resolve(binding_event(key))) for key in keys]
    except (OSError, ValueError) as error:
        return finish(str(error))
    # An empty v2 batch only reads the native boundary; it sends no input.
    probe = execute_campaign_keys(
        [], expected_dfroot=root, year=year, year_tick=year_tick, control_profile=NATIVE_PROFILE
    )
    result["boundary_probe"] = probe
    if probe.get("accepted") is not True:
        return finish("Displayed-key native boundary probe failed")
    before = probe["result"]["native_receipts"][-1]["after"]
    save = before["save_name"]
    for key, events in zip(keys, batches):
        try:
            read_binding_index(root)
        except (OSError, ValueError) as error:
            if result["keys_confirmed"]:
                result["command_mutation"] = "partial"
            return finish(str(error))
        result.update(command_mutation="unknown", keys_sent=None)
        try:
            receipt = run_lua_file(
                _hook_path("campaign_binding_set_v1.lua"),
                str(root),
                str(year),
                str(year_tick),
                save,
                *events,
                timeout=5,
            )
        except (DFHackError, OSError) as error:
            return finish(str(error))
        result["native_receipts"].append({"key": key, "events": events, "receipt": receipt})
        if not isinstance(receipt, dict):
            return finish("Malformed displayed-key native receipt")
        if receipt.get("ok") is not True:
            if (
                receipt.get("schema_version") == "fortgym.campaign-binding-set/v1"
                and receipt.get("command_mutation") == "not_attempted"
                and type(receipt.get("input_calls")) is int
                and receipt["input_calls"] == 0
            ):
                result["keys_sent"] = result["keys_confirmed"]
                result["command_mutation"] = (
                    "partial" if result["keys_confirmed"] else "not_attempted"
                )
            return finish(str(receipt.get("error") or "Native displayed-key input failed"))
        valid = (
            receipt.get("schema_version") == "fortgym.campaign-binding-set/v1"
            and receipt.get("events") == events
            and type(receipt.get("input_calls")) is int
            and receipt["input_calls"] == 1
            and receipt.get("command_mutation") == "completed"
        )
        for point in (receipt.get("before"), receipt.get("after")):
            valid = valid and (
                isinstance(point, dict)
                and point.get("dfroot") == str(root)
                and type(point.get("year")) is int
                and point["year"] == year
                and type(point.get("year_tick")) is int
                and point["year_tick"] == year_tick
                and point.get("paused") is True
                and point.get("save_name") == save
            )
        if not valid:
            return finish("Displayed-key receipt does not establish the requested boundary")
        result["keys_confirmed"] += 1
        result["keys_sent"] = result["keys_confirmed"]
        result["command_mutation"] = "completed"
        try:
            read_binding_index(root)
        except (OSError, ValueError) as error:
            # The acknowledged input happened, but its declared binding condition changed.
            result["command_mutation"] = "partial"
            return finish(str(error))
        time.sleep(0.05)  # UI cadence only, never world-time advancement.
    return finish()
