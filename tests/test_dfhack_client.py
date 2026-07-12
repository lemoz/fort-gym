from __future__ import annotations

from typing import Any

from fort_gym.bench.env.dfhack_client import (
    DFHackClient,
    screen_selection_hints,
    screen_to_text,
    screen_to_text_with_visual_hints,
)
from fort_gym.bench.env.state_reader import StateReader


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


def test_advance_threads_viewscreen_interrupt_options(monkeypatch) -> None:
    from fort_gym.bench.env import dfhack_client as client_module

    calls: list[dict[str, Any]] = []

    class AdvancingClient(DFHackClient):
        def _ensure_connection(self) -> None:
            return

        def get_state(self) -> dict[str, Any]:
            return {"time": 100}

    def fake_advance_ticks(ticks: int, **kwargs: Any) -> dict[str, Any]:
        calls.append({"ticks": ticks, **kwargs})
        return {"ok": False, "ticks_advanced": 0, "interrupted": True}

    monkeypatch.setattr(client_module, "advance_ticks_exact", fake_advance_ticks)

    client = AdvancingClient()
    state = client.advance(
        15,
        interrupt_on_viewscreen_transition=True,
        viewscreen_before="viewscreen_dwarfmodest",
    )

    assert state == {"time": 100}
    assert calls == [
        {
            "ticks": 15,
            "repause": True,
            "interrupt_on_viewscreen_transition": True,
            "viewscreen_before": "viewscreen_dwarfmodest",
        }
    ]
    assert client.last_tick_info["interrupted"] is True


def test_advance_preserves_default_delegation_signature(monkeypatch) -> None:
    from fort_gym.bench.env import dfhack_client as client_module

    calls: list[tuple[int, dict[str, Any]]] = []

    class AdvancingClient(DFHackClient):
        def _ensure_connection(self) -> None:
            return

        def get_state(self) -> dict[str, Any]:
            return {"time": 100}

    def fake_advance_ticks(ticks: int, **kwargs: Any) -> dict[str, Any]:
        calls.append((ticks, kwargs))
        return {"ok": True, "ticks_advanced": ticks}

    monkeypatch.setattr(client_module, "advance_ticks_exact", fake_advance_ticks)

    assert AdvancingClient().advance(15) == {"time": 100}
    assert calls == [(15, {"repause": True})]


def test_advance_threads_explicit_tick_limit(monkeypatch) -> None:
    from fort_gym.bench.env import dfhack_client as client_module

    calls: list[tuple[int, dict[str, Any]]] = []

    class AdvancingClient(DFHackClient):
        def _ensure_connection(self) -> None:
            return

        def get_state(self) -> dict[str, Any]:
            return {"time": 100}

    def fake_advance_ticks(ticks: int, **kwargs: Any) -> dict[str, Any]:
        calls.append((ticks, kwargs))
        return {"ok": True, "requested": ticks, "ticks_advanced": ticks}

    monkeypatch.setattr(client_module, "advance_ticks_exact", fake_advance_ticks)

    state = AdvancingClient().advance(
        2500,
        interrupt_on_viewscreen_transition=True,
        viewscreen_before="viewscreen_dwarfmodest",
        max_advance_ticks=2500,
    )

    assert state == {"time": 100}
    assert calls == [
        (
            2500,
            {
                "repause": True,
                "interrupt_on_viewscreen_transition": True,
                "viewscreen_before": "viewscreen_dwarfmodest",
                "max_advance_ticks": 2500,
            },
        )
    ]


def test_state_reader_preserves_dfhack_calendar_fields() -> None:
    class CalendarClient:
        def get_state(self) -> dict[str, Any]:
            return {
                "time": 1,
                "year": 8,
                "year_tick": 1,
                "stocks": {},
            }

    state = StateReader.from_dfhack(CalendarClient())  # type: ignore[arg-type]

    assert state["time"] == 1
    assert state["year"] == 8
    assert state["year_tick"] == 1


def _screen_from_rows(
    rows: list[str],
    *,
    highlighted_row: int | None = None,
    highlighted_cols: tuple[int, int] | None = None,
    highlighted_spans: list[tuple[int, int, int]] | None = None,
) -> dict[str, Any]:
    width = max(len(row) for row in rows)
    height = len(rows)
    padded_rows = [row.ljust(width) for row in rows]
    spans = list(highlighted_spans or [])
    if highlighted_row is not None and highlighted_cols is not None:
        spans.append((highlighted_row, highlighted_cols[0], highlighted_cols[1]))
    tiles: list[list[int]] = []
    for col in range(width):
        for row in range(height):
            ch = padded_rows[row][col]
            fg = 7
            bg = 0
            if any(span_row == row and start <= col <= end for span_row, start, end in spans):
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


def test_screen_visual_hints_skip_status_header() -> None:
    screen = _screen_from_rows(
        [
            "*PAUSED* Dwarf Fortress Date:250",
            "Carpenter's Workshop",
            "Construct Bed (b)",
        ],
        highlighted_spans=[(0, 0, 31), (2, 0, 16)],
    )

    text = screen_to_text_with_visual_hints(screen)

    assert "*PAUSED* Dwarf Fortress Date:250" in text
    assert "row 0" not in text
    assert "row 2 cols 0-16 fg=0 bg=7: Construct Bed (b)" in text
