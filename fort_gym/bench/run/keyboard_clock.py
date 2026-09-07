"""Attest a keyboard-selected build menu without advancing or dismissing it."""

from __future__ import annotations

SCHEMA = "fortgym.keyboard-menu-deferral/v1"
# This exact focus was observed holding the native calendar fixed during the
# 2026-09-07 campaign. Do not guess that every non-default focus blocks time.
BLOCKING_FOCUS = "dwarfmode/Build/Type"
NATIVE_VIEW = "<type: viewscreen_dwarfmodest>"


def validate_menu_deferral(
    receipt: dict, *, requested_ticks: int, before: dict, after: dict
) -> str | None:
    """Accept only a fresh, unchanged native boundary with no clock dispatch.

    A historical timeout is not this receipt and cannot be promoted into one.
    The chosen keys may have placed an order; only simulation is deferred.
    """
    if (
        receipt.get("schema_version") != SCHEMA
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
        native.get("focus") != BLOCKING_FOCUS
        or native.get("viewscreen_type") != NATIVE_VIEW
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
            or state.get("viewscreen_type") != "viewscreen_dwarfmodest"
            or type(state.get("year")) is not int
            or type(state.get("year_tick")) is not int
            or (state["year"], state["year_tick"])
            != (native["year"], native["year_tick"])
        ):
            return "menu_deferral_observation_mismatch"
    return None
