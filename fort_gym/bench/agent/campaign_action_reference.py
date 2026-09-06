"""Versioned, factual control documentation. Never a fortress-specific plan.

The installed adapter remains authoritative. These statements are grounded in
hook/designate_rect.lua and the map legend in campaign_encoder.py; normal native
job completion is separately exercised by the provider-free workshop fixture.
"""

NATIVE_DESIGNATIONS = """Native designation reference (native_designations/v1):
DIG.kind selects the operation; if omitted it defaults to dig.
- dig mines eligible natural WALL tiles (#). It does not clear already-open
  surface ground, floors (.), boulders/pebbles (p), shrubs, or tree trunks.
- channel designates eligible natural WALL or FLOOR tiles for channeling.
- chop designates visible TREE-material WALL tiles (tree trunks, T) for native
  woodcutting. Dwarf work produces logs over time; designation is not completion.
- gather designates visible living SHRUB tiles (,) for native plant gathering.
  Dead shrubs are not gatherable; dwarf work collects plants over time.
The rectangle is at most 30 by 30 tiles on one z-level. dig/channel reject the
whole rectangle if any selected tile is ineligible. They also reject hidden
tiles, map edges, buildings, player constructions, liquid/frozen tiles, trees and
unsupported native materials. chop/gather select eligible targets within the
rectangle and skip other readable non-target tiles; zero targets or unreadable
required tile data cause rejection. Coordinates and operation remain your choice.
This reference describes controls, not an action sequence or fortress strategy."""


def action_reference(profile: object) -> str:
    if profile == "none":
        return ""
    if profile == "native_designations/v1":
        return NATIVE_DESIGNATIONS
    raise ValueError("Unsupported local action reference")
