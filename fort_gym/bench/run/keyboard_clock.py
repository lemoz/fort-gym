"""Attest a keyboard-selected menu without advancing or dismissing it."""

from __future__ import annotations

import re

SCHEMA = "fortgym.keyboard-menu-deferral/v1"
MODAL_SCHEMA = "fortgym.keyboard-modal-deferral/v1"
DEFERRAL_SCHEMAS = (SCHEMA, MODAL_SCHEMA)
# These exact focuses held the native calendar fixed in retained native runs.
# Other dwarfmode focuses still try the clock; no menu is dismissed here.
BLOCKING_FOCUS = "dwarfmode/Build/Type"
WORKSHOP_JOB_FOCUS = "dwarfmode/QueryBuilding/Some/Workshop/AddJob"
BLOCKING_FOCI = frozenset((BLOCKING_FOCUS, WORKSHOP_JOB_FOCUS))
NATIVE_VIEW = "<type: viewscreen_dwarfmodest>"


def deferral_schema(native: dict) -> str | None:
    """Select factual feedback when the current UI cannot start the clock.

    The governed clock requires dwarfmode. A different identified native screen
    is not a malformed clock baseline: leave it to the model to navigate. Keep
    historical build-menu receipts separate from this newly supported case.
    """
    view, focus = native.get("viewscreen_type"), native.get("focus")
    if not isinstance(focus, str) or not focus:
        return None
    if view == NATIVE_VIEW:
        return SCHEMA if focus in BLOCKING_FOCI else None
    if (
        isinstance(view, str)
        and re.fullmatch(r"<type: viewscreen_\w+st>", view)
    ):
        return MODAL_SCHEMA
    return None


def validate_menu_deferral(
    receipt: dict, *, requested_ticks: int, before: dict, after: dict
) -> str | None:
    """Accept only a fresh, unchanged native boundary with no clock dispatch.

    A historical timeout is not this receipt and cannot be promoted into one.
    The chosen keys may have placed an order; only simulation is deferred.
    """
    if (
        receipt.get("schema_version") not in DEFERRAL_SCHEMAS
        or receipt.get("ok") is not False
        or receipt.get("deferred") is not True
        or receipt.get("error") != "blocking_native_menu"
        or receipt.get("clock_dispatched") is not False
        or receipt.get("timeout") is not False
        or type(requested_ticks) is not int
        or requested_ticks <= 0
        or type(receipt.get("requested")) is not int
        or receipt["requested"] != requested_ticks
        or type(receipt.get("ticks_advanced")) is not int
        or receipt["ticks_advanced"] != 0
    ):
        return "menu_deferral_contract_invalid"
    native, final = receipt.get("native_before"), receipt.get("native_after")
    if not isinstance(native, dict) or not isinstance(final, dict) or native != final:
        return "menu_deferral_native_boundary_changed"
    if (
        deferral_schema(native) != receipt["schema_version"]
        or native.get("paused") is not True
        or any(
            not isinstance(native.get(k), str) or not native[k]
            for k in ("dfroot", "save_name")
        )
        or type(native.get("year")) is not int
        or native["year"] < 0
        or type(native.get("year_tick")) is not int
        or not 0 <= native["year_tick"] < 403200
    ):
        return "menu_deferral_native_state_invalid"
    for state in (before, after):
        if (
            state.get("pause_state") is not True
            or "<type: " + str(state.get("viewscreen_type")) + ">" != native["viewscreen_type"]
            or type(state.get("year")) is not int
            or type(state.get("year_tick")) is not int
            or (state["year"], state["year_tick"])
            != (native["year"], native["year_tick"])
        ):
            return "menu_deferral_observation_mismatch"
    return None
