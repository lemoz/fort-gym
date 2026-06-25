from __future__ import annotations

from typing import Any

from fort_gym.bench.env.dfhack_client import (
    DFHackClient,
    screen_selection_hints,
    screen_to_text,
    screen_to_text_with_visual_hints,
)


class _TimeoutBuildingClient(DFHackClient):
    def _ensure_connection(self) -> None:
        return

    def _run_command(self, *_args: Any, **_kwargs: Any) -> None:
        raise TimeoutError("timed out")


def test_place_building_returns_failure_on_timeout() -> None:
    client = _TimeoutBuildingClient()

    ok, why = client.place_building("CarpenterWorkshop", 51, 36, 0)

    assert ok is False
    assert why == "timed out"


def _screen_from_rows(
    rows: list[str],
    *,
    highlighted_row: int | None = None,
    highlighted_cols: tuple[int, int] | None = None,
) -> dict[str, Any]:
    width = max(len(row) for row in rows)
    height = len(rows)
    padded_rows = [row.ljust(width) for row in rows]
    tiles: list[list[int]] = []
    for col in range(width):
        for row in range(height):
            ch = padded_rows[row][col]
            fg = 7
            bg = 0
            if (
                row == highlighted_row
                and highlighted_cols is not None
                and highlighted_cols[0] <= col <= highlighted_cols[1]
            ):
                fg = 0
                bg = 7
            tiles.append([ord(ch), fg, bg])
    return {"width": width, "height": height, "tiles": tiles}


def test_screen_text_keeps_plain_copy_screen_output() -> None:
    screen = _screen_from_rows(
        [
            "Carpenter's Workshop",
            "Make wooden shield",
            "Construct Bed (b)",
        ],
        highlighted_row=2,
        highlighted_cols=(0, 16),
    )

    assert screen_to_text(screen) == (
        "Carpenter's Workshop\nMake wooden shield\nConstruct Bed (b)"
    )


def test_screen_text_with_visual_hints_exposes_highlighted_menu_row() -> None:
    screen = _screen_from_rows(
        [
            "Carpenter's Workshop",
            "Make wooden shield",
            "Construct Bed (b)",
        ],
        highlighted_row=2,
        highlighted_cols=(0, 16),
    )

    hints = screen_selection_hints(screen)
    text = screen_to_text_with_visual_hints(screen)

    assert hints == [
        {
            "row": 2,
            "cols": [0, 16],
            "text": "Construct Bed (b)",
            "line": "Construct Bed (b)",
            "fg": 0,
            "bg": 7,
        }
    ]
    assert "== SCREEN VISUAL HINTS ==" in text
    assert "not as recommended actions" in text
    assert "row 2 cols 0-16 fg=0 bg=7: Construct Bed (b)" in text


def test_screen_text_with_visual_hints_omits_normal_colored_rows() -> None:
    screen = _screen_from_rows(["@....", "trees"])

    assert screen_selection_hints(screen) == []
    assert screen_to_text_with_visual_hints(screen) == "@....\ntrees"
