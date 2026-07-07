from __future__ import annotations

from fort_gym.bench.agent.minimap_render import minimap_data_url, render_minimap_png


def test_render_minimap_produces_png() -> None:
    png = render_minimap_png(["..WWW..", "..W.W..", "..WWW.."], [90, 87, 177])

    assert png is not None
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 500


def test_render_minimap_handles_queued_construction_glyph() -> None:
    from fort_gym.bench.agent.minimap_render import LEGEND_TEXT, TILE_STYLES

    assert "x" in TILE_STYLES
    assert "x=queued wall" in LEGEND_TEXT
    png = render_minimap_png(["..WxW..", "..x.x..", "..WxW.."], [90, 87, 177])
    assert png is not None and png[:8] == b"\x89PNG\r\n\x1a\n"


def test_minimap_data_url_prefix_and_fallbacks() -> None:
    url = minimap_data_url(
        {"map_rows": ["..WWW..", "..W.W.."], "map_origin": [90, 87, 177]}
    )
    assert url is not None and url.startswith("data:image/png;base64,")

    assert minimap_data_url({"map_rows": "junk", "map_origin": [1, 2, 3]}) is None
    assert minimap_data_url({"map_rows": [], "map_origin": [1, 2, 3]}) is None
