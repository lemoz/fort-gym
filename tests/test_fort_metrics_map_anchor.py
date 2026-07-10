from __future__ import annotations

from pathlib import Path


HOOK_SOURCE = (
    Path(__file__).resolve().parents[1] / "hook" / "fort_metrics.lua"
).read_text(encoding="utf-8")


def test_minimap_anchors_to_all_player_buildings() -> None:
    """Visible farm plots and other non-room buildings keep the fort in view."""

    assert "local map_anchor_buildings = {}" in HOOK_SOURCE
    assert "local function visible_building_bounds(bld)" in HOOK_SOURCE
    assert "for _, bld in ipairs(df.global.world.buildings.all) do" in HOOK_SOURCE
    assert "return visible_building_bounds(bld)" in HOOK_SOURCE
    assert "table.insert(map_anchor_buildings, anchor)" in HOOK_SOURCE
    assert "for _, bld in ipairs(map_anchor_buildings) do" in HOOK_SOURCE


def test_citizens_anchor_minimap_only_before_any_building_exists() -> None:
    citizen_anchor_guard = """if #map_anchor_buildings == 0
            and map_tile_visible(cpos.x, cpos.y, cpos.z) then
          anchor_z_counts[unit.pos.z] = (anchor_z_counts[unit.pos.z] or 0) + 1
        end"""

    assert citizen_anchor_guard in HOOK_SOURCE


def test_minimap_hidden_tiles_cannot_affect_bounds_or_render_markers() -> None:
    assert "local function map_tile_visible(x, y, z)" in HOOK_SOURCE
    assert "local visible_citizen_positions = {}" in HOOK_SOURCE
    assert "for _, cpos in ipairs(visible_citizen_positions) do" in HOOK_SOURCE
    assert "and map_tile_visible(tonumber(cx), tonumber(cy), tonumber(cz))" in HOOK_SOURCE

    render_start = HOOK_SOURCE.index("local function render_tile")
    render_end = HOOK_SOURCE.index("local anchor_z, best", render_start)
    render_source = HOOK_SOURCE[render_start:render_end]
    assert render_source.index("if shape == nil or hidden then") < render_source.index(
        "elseif citizen_tile_lookup[key] then"
    )
    assert render_source.index("if shape == nil or hidden then") < render_source.index(
        "elseif building_at(x, y, z) then"
    )
