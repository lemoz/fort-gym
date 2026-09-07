"""Campaign-only read-only view selection, without widening historical controls."""

from __future__ import annotations

from copy import deepcopy

from .actions import parse_action

DECISION_PROFILE = "campaign_action/v2"
OBSERVATION_PROFILE = "campaign_state/v3"
MAP_SCHEMA = "fortgym.campaign-map-view/v1"
MAX_VIEW_SIDE = 34
VIEW_FIELDS = ("origin", "size")
VIEW_INSTRUCTION = """
VIEW: params {origin:[x,y,z],size:[width,height]}, with advance_ticks exactly 0.
Choose any in-map region and z-level; width and height are 1-34 tiles. This reads
terrain without changing the game, revealing hidden tiles or moving dwarves.
The model-selected view persists across decisions and checkpoints, alongside
the fort overview. A blank tile is hidden/unreadable, not empty floor. The view
does not report units, buildings, items or pathfinding; use the other native
observations for those facts. Map dimensions are in tiles, with zero-based x,y,z.
Invalid or out-of-map requests receive feedback, not an automatically chosen view.
"""


class MapObservationError(ValueError):
    """The native reader returned inconsistent evidence, not a model gameplay failure."""

    terminal_code = "campaign_map_observation_invalid"


def view_selection(value: object) -> dict:
    """Validate a selected rectangle without coercion, clamping or retargeting."""
    if not isinstance(value, dict) or set(value) != set(VIEW_FIELDS):
        raise ValueError("VIEW requires exactly origin:[x,y,z] and size:[width,height]")
    origin, size = value["origin"], value["size"]
    if (
        not isinstance(origin, list)
        or len(origin) != 3
        or any(type(n) is not int or n < 0 for n in origin)
        or not isinstance(size, list)
        or len(size) != 2
        or any(type(n) is not int or not 1 <= n <= MAX_VIEW_SIDE for n in size)
    ):
        raise ValueError("VIEW requires nonnegative integer coordinates and sizes 1-34")
    return {"origin": list(origin), "size": list(size)}


def parse_campaign_action(payload: dict, *, max_advance_ticks: int, allow_view: bool) -> dict:
    if str(payload.get("type") or "").strip().upper() != "VIEW":
        return parse_action(payload, max_advance_ticks=max_advance_ticks)
    if not allow_view:
        raise ValueError("VIEW is not part of this campaign's declared interface")
    if type(payload.get("advance_ticks")) is not int or payload["advance_ticks"] != 0:
        raise ValueError("VIEW requires advance_ticks == 0")
    return {
        "type": "VIEW",
        "params": view_selection(payload.get("params")),
        "advance_ticks": 0,
        **{
            key: payload[key]
            for key in ("intent", "objective", "plan_step", "memory_update")
            if isinstance(payload.get(key), str)
        },
    }


def validate_map_read(value: dict, selection: dict | None, state: dict) -> dict:
    """Bind read-only map evidence to this paused calendar and exact selection."""
    if not isinstance(value, dict) or value.get("schema_version") != MAP_SCHEMA:
        raise MapObservationError("Map inspection lacks its versioned native receipt")
    if value.get("ok") is False:
        return deepcopy(value)
    if (
        value.get("ok") is not True
        or value.get("scope") != "visible_terrain_only"
        or value.get("error") is not None
    ):
        raise MapObservationError("Map inspection lacks its visible-terrain scope")
    if (
        value.get("paused") is not True
        or type(value.get("year")) is not int
        or type(value.get("year_tick")) is not int
        or value.get("year") != state.get("year")
        or value.get("year_tick") != state.get("year_tick")
        or state.get("pause_state") is not True
    ):
        raise MapObservationError("Map inspection differs from the paused native calendar")
    dims = value.get("map_dimensions")
    if (
        not isinstance(dims, list)
        or len(dims) != 3
        or any(type(n) is not int or n <= 0 for n in dims)
    ):
        raise MapObservationError("Map dimensions must be positive native tile counts")
    if selection is None:
        if value.get("active") is not False or any(
            key in value for key in ("map_origin", "map_size", "map_rows")
        ):
            raise MapObservationError("Map inspection invented an unselected view")
        return deepcopy(value)
    expected = view_selection(selection)
    x, y, z = expected["origin"]
    width, height = expected["size"]
    rows = value.get("map_rows")
    if (
        value.get("active") is not True
        or any(
            not isinstance(value.get(key), list) or any(type(n) is not int for n in value[key])
            for key in ("map_origin", "map_size")
        )
        or value.get("map_origin") != expected["origin"]
        or value.get("map_size") != expected["size"]
        or x + width > dims[0]
        or y + height > dims[1]
        or z >= dims[2]
        or not isinstance(rows, list)
        or len(rows) != height
        or any(not isinstance(row, str) or len(row) != width for row in rows)
    ):
        raise MapObservationError("Map inspection differs from the exact requested rectangle")
    counts: list[int] = []
    for key in ("visible_tiles", "hidden_tiles", "unreadable_tiles"):
        count = value.get(key)
        if type(count) is not int or count < 0:
            raise MapObservationError("Map inspection has inconsistent tile completeness")
        counts.append(count)
    if (
        sum(counts) != width * height
        or type(value.get("scan_complete")) is not bool
        or value["scan_complete"] != (value["unreadable_tiles"] == 0)
        or sum(row.count(" ") for row in rows) != value["hidden_tiles"] + value["unreadable_tiles"]
        or any(char not in " .#T<>X^~,spiwL?" for row in rows for char in row)
    ):
        raise MapObservationError("Map inspection has inconsistent tile completeness")
    return deepcopy(value)
