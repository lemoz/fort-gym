"""Lossless model-visible screen profiles, independent of internal fortress state.

The text profile preserves one Unicode character per tile, full screen geometry,
and all foreground/background colors. It does not classify terrain or pick a
menu option. The original raw-tile profile remains available for comparison.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy

RAW_PROFILE = "native_screen_tiles/v1"
TEXT_PROFILE = "native_screen_text/v1"
PROFILES = (RAW_PROFILE, TEXT_PROFILE)

# CP437's control-byte positions are rendered as glyphs by Classic DF, not
# interpreted as terminal controls. Code zero shares a blank with code 32;
# an explicit override below preserves that difference in the raw capture.
_LOW_GLYPHS = " ☺☻♥♦♣♠•◘○◙♂♀♪♫☼►◄↕‼¶§▬↨↑↓→←∟↔▲▼"
_GLYPHS = (
    _LOW_GLYPHS
    + bytes(range(32, 127)).decode("cp437")
    + "⌂"
    + bytes(range(128, 256)).decode("cp437")
)
_CODES = {glyph: index for index, glyph in enumerate(_GLYPHS)}


def _dimensions(width: object, height: object) -> tuple[int, int]:
    if (
        type(width) is not int
        or type(height) is not int
        or not 1 <= width <= 300
        or not 1 <= height <= 150
    ):
        raise ValueError("Invalid native screen dimensions")
    return width, height


def raw_screen(screen: object) -> dict:
    """Validate and retain exactly the actual capture, not a requested viewport."""
    if not isinstance(screen, dict):
        raise ValueError("Missing native screen capture")
    width, height = _dimensions(screen.get("width"), screen.get("height"))
    tiles = screen.get("tiles")
    if not isinstance(tiles, list) or len(tiles) != width * height:
        raise ValueError("Native screen dimensions and tile count must agree")
    for tile in tiles:
        if (
            not isinstance(tile, list)
            or len(tile) != 3
            or any(type(value) is not int or value < 0 for value in tile)
        ):
            raise ValueError("Every screen tile needs character, foreground and background")
    return {
        "observation_profile": RAW_PROFILE,
        "tile_order": "column_major",
        "width": width,
        "height": height,
        "tiles": deepcopy(tiles),
    }


def text_screen(screen: object) -> dict:
    """Readable rows plus color spans; every captured tile can be reconstructed."""
    capture = raw_screen(screen)
    width, height, tiles = capture["width"], capture["height"], capture["tiles"]
    # Stable first-seen tie breaking, independent of hash randomization.
    default = Counter((tile[1], tile[2]) for tile in tiles).most_common(1)[0][0]
    blank_counts = Counter(tile[0] for tile in tiles if tile[0] in {0, 32})
    blank_code = 0 if blank_counts[0] > blank_counts[32] else 32
    rows, spans, overrides = [], [], []
    for y in range(height):
        row = [tiles[x * height + y] for x in range(width)]
        glyphs = []
        for x, (code, _fg, _bg) in enumerate(row):
            glyph = _GLYPHS[code] if code < len(_GLYPHS) else "�"
            glyphs.append(glyph)
            recovered_code = blank_code if glyph == " " else _CODES.get(glyph)
            if recovered_code != code:
                overrides.append([x, y, code])
        rows.append("".join(glyphs))
        x = 0
        while x < width:
            fg, bg = row[x][1:]
            end = x + 1
            while end < width and row[end][1:] == [fg, bg]:
                end += 1
            if (fg, bg) != default:
                spans.append([y, x, end, fg, bg])
            x = end
    return {
        "observation_profile": TEXT_PROFILE,
        "width": width,
        "height": height,
        "rows": rows,
        "blank_code": blank_code,
        "default_colors": list(default),
        "color_spans": spans,
        "glyph_overrides": overrides,
    }


def expand_text_screen(value: object) -> dict:
    """Reconstruct raw tiles for fidelity tests and replay, never game mutation."""
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "observation_profile",
            "width",
            "height",
            "rows",
            "default_colors",
            "color_spans",
            "glyph_overrides",
            "blank_code",
        }
        or value.get("observation_profile") != TEXT_PROFILE
    ):
        raise ValueError("Unsupported compact screen record")
    width, height = _dimensions(value["width"], value["height"])
    rows, colors, blank_code = value["rows"], value["default_colors"], value["blank_code"]
    if (
        not isinstance(rows, list)
        or len(rows) != height
        or any(not isinstance(row, str) or len(row) != width for row in rows)
        or not isinstance(colors, list)
        or len(colors) != 2
        or any(type(color) is not int or color < 0 for color in colors)
        or type(blank_code) is not int
        or blank_code not in {0, 32}
    ):
        raise ValueError("Invalid compact screen geometry or colors")
    overrides, spans = value["glyph_overrides"], value["color_spans"]
    if (
        not isinstance(overrides, list)
        or not isinstance(spans, list)
        or len(overrides) > width * height
        or len(spans) > width * height
    ):
        raise ValueError("Invalid compact screen spans or glyph overrides")
    glyph_codes = {}
    for record in overrides:
        if (
            not isinstance(record, list)
            or len(record) != 3
            or any(type(n) is not int or n < 0 for n in record)
        ):
            raise ValueError("Invalid glyph override")
        x, y, code = record
        if x >= width or y >= height or (x, y) in glyph_codes:
            raise ValueError("Duplicate or out-of-bounds glyph override")
        glyph_codes[x, y] = code
    tiles = []
    for x in range(width):
        for y in range(height):
            default_code = blank_code if rows[y][x] == " " else _CODES.get(rows[y][x])
            code = glyph_codes.get((x, y), default_code)
            if code is None:
                raise ValueError("A non-CP437 glyph requires its original code")
            expected = _GLYPHS[code] if code < len(_GLYPHS) else "�"
            if expected != rows[y][x]:
                raise ValueError("Glyph override contradicts the visible row")
            tiles.append([code, *colors])
    colored = set()
    for span in spans:
        if (
            not isinstance(span, list)
            or len(span) != 5
            or any(type(n) is not int or n < 0 for n in span)
        ):
            raise ValueError("Invalid color span")
        y, start, end, fg, bg = span
        if y >= height or not start < end <= width:
            raise ValueError("Color span is outside the screen")
        for x in range(start, end):
            if (x, y) in colored:
                raise ValueError("Color spans overlap")
            colored.add((x, y))
            tiles[x * height + y][1:] = [fg, bg]
    return raw_screen({"width": width, "height": height, "tiles": tiles})


def encode_screen(screen: object, profile: str) -> dict:
    if profile == RAW_PROFILE:
        return raw_screen(screen)
    if profile == TEXT_PROFILE:
        return text_screen(screen)
    raise ValueError("Unsupported screen observation profile")
