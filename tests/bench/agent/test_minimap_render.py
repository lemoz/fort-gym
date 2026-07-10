from __future__ import annotations

import base64
import io

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


def test_render_minimap_distinguishes_frozen_liquid() -> None:
    from fort_gym.bench.agent.minimap_render import LEGEND_TEXT, TILE_STYLES

    assert "i" in TILE_STYLES
    assert "i=frozen liquid" in LEGEND_TEXT
    assert TILE_STYLES["i"] != TILE_STYLES["."]
    png = render_minimap_png(["..iii..", "..i.i..", "..iii.."], [90, 87, 177])
    assert png is not None and png[:8] == b"\x89PNG\r\n\x1a\n"


def test_render_minimap_distinguishes_other_occupied_buildings() -> None:
    from fort_gym.bench.agent.minimap_render import LEGEND_TEXT, TILE_STYLES

    assert "o" in TILE_STYLES
    assert "o=occupied" in LEGEND_TEXT
    assert TILE_STYLES["o"] != TILE_STYLES["."]
    png = render_minimap_png(["..ooo..", "..o.o..", "..ooo.."], [90, 87, 177])
    assert png is not None and png[:8] == b"\x89PNG\r\n\x1a\n"


def test_render_minimap_distinguishes_shrubs_saplings_and_loose_rock() -> None:
    from PIL import Image, ImageDraw

    from fort_gym.bench.agent.minimap_render import LEGEND_TEXT, RULER, TILE_STYLES

    assert ",=gatherable shrub" in LEGEND_TEXT
    assert "s=sapling" in LEGEND_TEXT
    assert "p=loose rock" in LEGEND_TEXT
    assert len({TILE_STYLES[","][0], TILE_STYLES["s"][0], TILE_STYLES["p"][0]}) == 3
    png = render_minimap_png([".,sp."], [90, 87, 177])
    assert png is not None and png[:8] == b"\x89PNG\r\n\x1a\n"
    image = Image.open(io.BytesIO(png))
    legend_width = ImageDraw.Draw(image).textbbox((0, 0), LEGEND_TEXT)[2]
    assert image.width >= RULER + legend_width


def test_render_minimap_distinguishes_vertical_access_geometry() -> None:
    from fort_gym.bench.agent.minimap_render import LEGEND_TEXT, TILE_STYLES

    for glyph in ("<", ">", "X", "^"):
        assert glyph in TILE_STYLES
    assert "X=up/down" in LEGEND_TEXT
    assert "^=ramp" in LEGEND_TEXT
    png = render_minimap_png([".<>", ".X^"], [90, 87, 177])
    assert png is not None and png[:8] == b"\x89PNG\r\n\x1a\n"


def test_minimap_data_url_prefix_and_fallbacks() -> None:
    url = minimap_data_url(
        {"map_rows": ["..WWW..", "..W.W.."], "map_origin": [90, 87, 177]}
    )
    assert url is not None and url.startswith("data:image/png;base64,")

    assert minimap_data_url({"map_rows": "junk", "map_origin": [1, 2, 3]}) is None
    assert minimap_data_url({"map_rows": [], "map_origin": [1, 2, 3]}) is None


def test_minimap_data_url_stacks_model_focused_level_maps() -> None:
    from PIL import Image

    single_url = minimap_data_url(
        {"map_rows": ["...", ".@."], "map_origin": [90, 87, 177]}
    )
    stacked_url = minimap_data_url(
        {
            "map_rows": ["...", ".@."],
            "map_origin": [90, 87, 177],
            "access_level_maps": [
                {"rows": ["###", "#^#"], "origin": [90, 87, 176]}
            ],
        }
    )

    assert single_url is not None and stacked_url is not None
    single = Image.open(io.BytesIO(base64.b64decode(single_url.split(",", 1)[1])))
    stacked = Image.open(io.BytesIO(base64.b64decode(stacked_url.split(",", 1)[1])))
    assert stacked.height > single.height
