"""Render the fort minimap character grid as a PNG for vision models.

The image is a faithful re-rendering of the same ``map_rows`` recorded in the
trace — colored cells with coordinate rulers and a legend. It adds no
information beyond the character grid; it only changes the modality.
"""

from __future__ import annotations

import base64
import io
from typing import Any, Dict, Optional, Sequence

CELL = 24
RULER = 26
LEGEND_HEIGHT = 30

# char -> (fill colour, letter to draw or None)
TILE_STYLES: Dict[str, tuple] = {
    "#": ((90, 84, 74), None),      # natural wall — dark earth
    "W": ((214, 106, 40), None),    # player-built wall — orange
    "x": ((240, 178, 122), "x"),    # queued wall/floor — pale orange
    "T": ((34, 102, 48), "T"),      # tree trunk — deep green
    ".": ((222, 210, 180), None),   # open floor — light tan
    "i": ((116, 194, 214), "i"),    # frozen liquid — cyan
    ",": ((176, 200, 150), None),   # gatherable shrub — pale green
    "s": ((55, 150, 75), "s"),      # sapling — green
    "p": ((135, 130, 120), "p"),    # boulder/pebbles — gray
    "<": ((170, 150, 90), "<"),     # up stair
    ">": ((170, 150, 90), ">"),     # down stair
    "X": ((190, 165, 85), "X"),     # up/down stair
    "^": ((155, 135, 80), "^"),     # ramp or ramp top
    "~": ((110, 130, 160), None),   # impassable — blue-gray
    " ": ((20, 20, 20), None),      # unknown/out of range — near-black
    "b": ((150, 60, 140), "b"),     # bed
    "t": ((60, 110, 170), "t"),     # table
    "c": ((60, 150, 170), "c"),     # chair
    "d": ((120, 90, 50), "d"),      # door
    "w": ((40, 70, 160), "w"),      # workshop
    "o": ((105, 75, 125), "o"),     # other occupied building
    "@": ((250, 250, 250), "@"),    # dwarf
    "?": ((200, 40, 40), "?"),
}

LEGEND_TEXT = (
    "W=your wall  x=queued wall (building)  #=natural wall  T=tree  "
    "b=bed t=table c=chair d=door w=workshop o=occupied  @=dwarf  .=floor  "
    "i=frozen liquid  ,=gatherable shrub  s=sapling  p=loose rock  "
    "<=up stair >=down stair X=up/down ^=ramp"
)


def render_minimap_png(
    map_rows: Sequence[str],
    map_origin: Sequence[int],
) -> Optional[bytes]:
    """Return PNG bytes for the minimap, or None if rendering is unavailable."""

    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    if not map_rows or len(map_origin) < 3:
        return None

    rows = [str(row) for row in map_rows]
    height = len(rows)
    width = max(len(row) for row in rows)
    if width == 0 or height == 0:
        return None
    ox, oy, oz = int(map_origin[0]), int(map_origin[1]), int(map_origin[2])

    measurement_canvas = Image.new("RGB", (1, 1))
    measurement_draw = ImageDraw.Draw(measurement_canvas)
    legend_width = measurement_draw.textbbox((0, 0), LEGEND_TEXT)[2]
    img_w = max(RULER + width * CELL, RULER + legend_width + 4)
    img_h = RULER + height * CELL + LEGEND_HEIGHT
    image = Image.new("RGB", (img_w, img_h), (12, 12, 12))
    draw = ImageDraw.Draw(image)

    for row_index, row in enumerate(rows):
        for col_index in range(width):
            char = row[col_index] if col_index < len(row) else " "
            fill, letter = TILE_STYLES.get(char, TILE_STYLES["?"])
            x0 = RULER + col_index * CELL
            y0 = RULER + row_index * CELL
            draw.rectangle(
                [x0, y0, x0 + CELL - 1, y0 + CELL - 1],
                fill=fill,
                outline=(40, 40, 40),
            )
            if letter:
                text_fill = (20, 20, 20) if char == "@" else (255, 255, 255)
                draw.text((x0 + CELL // 3, y0 + CELL // 5), letter, fill=text_fill)

    # coordinate rulers every 2 cells, full coordinates for anchor rows/cols
    for col_index in range(0, width, 2):
        draw.text(
            (RULER + col_index * CELL + 2, 4),
            str((ox + col_index) % 100),
            fill=(220, 220, 220),
        )
    for row_index in range(0, height, 2):
        draw.text(
            (2, RULER + row_index * CELL + 4),
            str((oy + row_index) % 100),
            fill=(220, 220, 220),
        )
    draw.text((2, 4), f"z={oz}", fill=(240, 220, 120))
    draw.text((RULER, img_h - LEGEND_HEIGHT + 8), LEGEND_TEXT, fill=(230, 230, 230))

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def minimap_data_url(fort: Dict[str, Any]) -> Optional[str]:
    """Return a PNG data URL for the main and model-focused level maps."""

    map_rows = fort.get("map_rows")
    map_origin = fort.get("map_origin")
    if not isinstance(map_rows, list) or not isinstance(map_origin, (list, tuple)):
        return None
    panels: list[bytes] = []
    main_png = render_minimap_png(map_rows, map_origin)
    if main_png is None:
        return None
    panels.append(main_png)

    access_maps = fort.get("access_level_maps")
    if isinstance(access_maps, list):
        for level in access_maps[:2]:
            if not isinstance(level, dict):
                continue
            rows = level.get("rows")
            origin = level.get("origin")
            if not isinstance(rows, list) or not isinstance(origin, (list, tuple)):
                continue
            panel = render_minimap_png(rows, origin)
            if panel is not None:
                panels.append(panel)

    png = main_png
    if len(panels) > 1:
        try:
            from PIL import Image

            images = [Image.open(io.BytesIO(panel)).convert("RGB") for panel in panels]
            width = max(panel.width for panel in images)
            height = sum(panel.height for panel in images) + 8 * (len(images) - 1)
            stacked = Image.new("RGB", (width, height), (8, 8, 8))
            y = 0
            for panel in images:
                stacked.paste(panel, (0, y))
                y += panel.height + 8
            buffer = io.BytesIO()
            stacked.save(buffer, format="PNG")
            png = buffer.getvalue()
        except (ImportError, OSError):
            png = main_png

    encoded = base64.b64encode(png).decode("ascii")
    return f"data:image/png;base64,{encoded}"


__all__ = ["render_minimap_png", "minimap_data_url"]
