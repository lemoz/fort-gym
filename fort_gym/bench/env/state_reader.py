"""Utilities to obtain structured state from DFHack or mocks."""

from __future__ import annotations

from typing import Any, Dict

from .dfhack_client import DFHackClient


class StateReader:
    """Collect state snapshots from configured backends."""

    @staticmethod
    def from_dfhack(client: DFHackClient) -> Dict[str, Any]:
        """Retrieve state via DFHack client."""

        raw = client.get_state()
        stocks = raw.get("stocks") or {}
        normalized = {
            "time": raw.get("time", 0),
            "year": raw.get("year", 0),
            "year_tick": raw.get("year_tick", raw.get("time", 0)),
            "population": raw.get("population", 0),
            "stocks": {
                "food": stocks.get("food", 0),
                "drink": stocks.get("drink", 0),
                "wood": stocks.get("wood", 0),
                "stone": stocks.get("stone", 0),
                # usable = not claimed by jobs / locked in (pending) buildings;
                # this whitelist silently dropped the fields when they shipped,
                # so G6 attempt 3 ran without them (WDSLL 2026-07-08)
                "wood_usable": stocks.get("wood_usable"),
                "stone_usable": stocks.get("stone_usable"),
                "wealth": stocks.get("wealth", raw.get("wealth")),
            },
            "risks": raw.get("risks", []),
            "reminders": raw.get("reminders", []),
            "recent_events": raw.get("recent_events", []),
            "hostiles": raw.get("hostiles", False),
            "dead": raw.get("dead", 0),
            "map_bounds": raw.get("map_bounds", (0, 0, 0)),
            "pause_state": raw.get("pause_state"),
            "viewscreen_type": raw.get("viewscreen_type", "unknown"),
            "work": raw.get("work", {}),
        }
        workshops = raw.get("workshops") if isinstance(raw.get("workshops"), dict) else {}
        normalized["workshops"] = {"CarpenterWorkshop": workshops.get("CarpenterWorkshop", 0)}
        return normalized

    @staticmethod
    def from_mock(mock) -> Dict[str, Any]:
        """Retrieve state via mock environment."""

        return mock.observe()
