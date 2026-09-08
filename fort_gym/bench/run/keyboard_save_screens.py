"""Identified DFHack screens for the opt-in v4 menu-preserving save.

DFHack 0.47.05-r8 wraps its own screens as the base viewscreen type. Its
getFocusString identifies those screens with a dfhack/ prefix. Never accept an
unidentified base viewscreen, a dismissed screen, or a changed parent focus.
"""

from __future__ import annotations

import re
from typing import Any

from .campaign_save import CampaignSaveError

SCREEN_IDENTITY_LUA = r"""
local function screen_identity(screen, address)
    local typename = tostring(screen._type)
    local focus = dfhack.gui.getFocusString(screen)
    local native = typename:match('^<type: viewscreen_.*st>$') ~= nil
    local owned = typename == '<type: viewscreen>'
        and type(focus) == 'string' and focus:match('^dfhack/.+') ~= nil
    assert(native or owned, 'Unidentified screen in snapshot stack: ' .. typename)
    assert(type(focus) == 'string' and #focus > 0, 'Missing screen focus')
    local dismissed = dfhack.screen.isDismissed(screen)
    assert(dismissed == false, 'Snapshot cannot hide a dismissed screen')
    return {type=typename, address=address, focus=focus,
            kind=native and 'native' or 'dfhack', dismissed=dismissed}
end
"""


def validate_identified_stack(stack: Any) -> None:
    if not isinstance(stack, list) or not 1 <= len(stack) <= 32:
        raise CampaignSaveError("Identified menu stack is invalid")
    addresses = set()
    for index, screen in enumerate(stack):
        if not isinstance(screen, dict) or set(screen) != {
            "type", "address", "focus", "kind", "dismissed"
        }:
            raise CampaignSaveError("Identified menu screen fields are invalid")
        typename, focus, address = screen["type"], screen["focus"], screen["address"]
        if (
            not isinstance(typename, str)
            or not isinstance(focus, str) or not focus
            or not isinstance(address, str) or not address or address in addresses
            or screen["dismissed"] is not False
        ):
            raise CampaignSaveError("Identified menu screen identity is invalid")
        native = re.fullmatch(r"<type: viewscreen_\w+st>", typename) is not None
        owned = typename == "<type: viewscreen>" and re.fullmatch(r"dfhack/.+", focus) is not None
        if not (native and screen["kind"] == "native" or owned and screen["kind"] == "dfhack"):
            raise CampaignSaveError("Unidentified screen in snapshot stack")
        if typename == "<type: viewscreen_dwarfmodest>" and index != len(stack) - 1:
            raise CampaignSaveError("Fortress must terminate the identified stack")
        addresses.add(address)
    if stack[-1]["type"] != "<type: viewscreen_dwarfmodest>":
        raise CampaignSaveError("Identified menu stack lacks a fortress ancestor")
