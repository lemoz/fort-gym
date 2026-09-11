import json
import random
from copy import deepcopy

import pytest

from fort_gym.bench.env.screen_observation import (
    RAW_PROFILE,
    TEXT_PROFILE,
    encode_screen,
    expand_text_screen,
    raw_screen,
    text_screen,
)


def capture(width=80, height=25, blank=32):
    return {
        "width": width,
        "height": height,
        "tiles": [[blank, 7, 0] for _ in range(width * height)],
    }


def test_all_cp437_codes_and_colors_roundtrip_without_ascii_substitution():
    screen = capture(16, 16)
    screen["tiles"] = [[code, code % 16, code // 16] for code in range(256)]
    compact = text_screen(screen)
    assert expand_text_screen(compact) == raw_screen(screen)
    assert compact["rows"][3][0] == "♥"
    assert compact["rows"][4][0] == "♦"
    assert all(len(row) == 16 for row in compact["rows"])


@pytest.mark.parametrize("width,height", [(80, 25), (120, 40), (160, 50)])
def test_asymmetric_screen_preserves_corners_and_selected_text(width, height):
    screen = capture(width, height)
    for x, y, code in [
        (0, 0, 65),
        (width - 1, 0, 66),
        (0, height - 1, 67),
        (width - 1, height - 1, 68),
    ]:
        screen["tiles"][x * height + y] = [code, 15, 3]
    for x, char in enumerate("Add new task", start=4):
        screen["tiles"][x * height + 3] = [ord(char), 15, 1]
    compact = text_screen(screen)
    assert compact["rows"][0][0] == "A"
    assert compact["rows"][0][-1] == "B"
    assert compact["rows"][-1][0] == "C"
    assert compact["rows"][-1][-1] == "D"
    assert compact["rows"][3][4:16] == "Add new task"
    assert [3, 4, 16, 15, 1] in compact["color_spans"]
    assert expand_text_screen(compact) == raw_screen(screen)


@pytest.mark.parametrize("blank", [0, 32])
def test_blank_heavy_menu_compacts_without_losing_blank_code(blank):
    screen = capture(blank=blank)
    compact = text_screen(screen)
    assert compact["blank_code"] == blank
    assert compact["glyph_overrides"] == []
    assert expand_text_screen(compact) == raw_screen(screen)
    assert len(json.dumps(compact)) < len(json.dumps(raw_screen(screen))) * 0.15


def test_mixed_blank_codes_and_unknown_glyph_preserved():
    screen = capture(3, 2, blank=0)
    screen["tiles"][1][0] = 32
    screen["tiles"][3][0] = 999
    compact = text_screen(screen)
    assert compact["blank_code"] == 0
    assert [0, 1, 32] in compact["glyph_overrides"]
    assert [1, 1, 999] in compact["glyph_overrides"]
    assert expand_text_screen(compact) == raw_screen(screen)


def test_randomized_geometry_colors_and_glyphs_roundtrip():
    rng = random.Random(9281)
    for _ in range(35):
        width, height = rng.randint(1, 75), rng.randint(1, 40)
        screen = capture(width, height)
        screen["tiles"] = [
            [rng.randint(0, 300), rng.randrange(16), rng.randrange(16)] for _ in screen["tiles"]
        ]
        assert expand_text_screen(text_screen(screen)) == raw_screen(screen)


def test_inputs_are_not_mutated_and_internal_state_never_added():
    screen = capture(3, 3)
    screen["internal"] = {"hidden": True}
    original = deepcopy(screen)
    for profile in (RAW_PROFILE, TEXT_PROFILE):
        output = encode_screen(screen, profile)
        assert "internal" not in output
        assert output["observation_profile"] == profile
    assert screen == original
    with pytest.raises(ValueError):
        encode_screen(screen, "unknown")


@pytest.mark.parametrize(
    "mutation",
    [
        "short_row",
        "extra_row",
        "bad_color",
        "bad_blank",
        "overlap",
        "out_of_bounds",
        "duplicate_glyph",
        "contradictory_glyph",
        "unknown_glyph",
    ],
)
def test_corrupt_compact_record_cannot_be_accepted_as_faithful(mutation):
    value = text_screen(capture(3, 3))
    if mutation == "short_row":
        value["rows"][0] = " "
    elif mutation == "extra_row":
        value["rows"].append("   ")
    elif mutation == "bad_color":
        value["default_colors"][0] = True
    elif mutation == "bad_blank":
        value["blank_code"] = True
    elif mutation == "overlap":
        value["color_spans"] = [[0, 0, 2, 1, 2], [0, 1, 2, 3, 4]]
    elif mutation == "out_of_bounds":
        value["color_spans"] = [[0, 0, 4, 1, 2]]
    elif mutation == "duplicate_glyph":
        value["glyph_overrides"] = [[0, 0, 0], [0, 0, 0]]
    elif mutation == "contradictory_glyph":
        value["glyph_overrides"] = [[0, 0, 65]]
    else:
        value["rows"][0] = "�  "
    with pytest.raises(ValueError):
        expand_text_screen(value)
